<?php

namespace App\Http\Controllers;

use App\Enums\QueuedDemoStatus;
use App\Http\Controllers\ImageController;
use App\Models\{
    Demo,
    AdminDemo,
    AdminDemoPaths,
    AdminQueuedDemo,
    AdminQueuedDemoChunk,
    QueuedDemo,
    AdminDemoTactic,
    DemoRound,
    DemoFolder
};
use Illuminate\Http\{
    Request,
    JsonResponse
};
use Illuminate\Support\Facades\Auth;
use Inertia\Inertia;

class DemoController extends Controller
{
    private $imageController;
    public function __construct(ImageController $imageController)
    {
        $this->imageController = $imageController;
    }

    public function index(Request $request)
    {
        $user = $request->user();
        $teams = $user->teams;

        $hideFolderDemos = $request->boolean('hideFolderDemos');

        $demos = $this->getDemos($teams, $hideFolderDemos);
        $queuedDemos = QueuedDemo::where('owner', $user->id)->whereIn('status', [QueuedDemoStatus::Uploading, QueuedDemoStatus::Pending, QueuedDemoStatus::Failed, QueuedDemoStatus::Processing])->get();

        $demos = array_merge($queuedDemos->toArray(), $demos->toArray());
        return new JsonResponse($demos, JsonResponse::HTTP_OK);
    }

    public function show(Request $request, int $id)
    {
        ini_set('memory_limit', '1024M');
        $teams = $request->user()->teams;
        $teamIds = $teams->pluck('id')->toArray();
        
        $demo = $this->secureDemoQuery($teamIds)
            ->with(['rounds' => function ($query) {
                $query->orderBy('round_index', 'asc')
                      ->where('round_index', '>', 0)
                      ->select('meta', 'demo_id', 'round_index');
            }, 'stats', 'utility', 'heatmap', 'lastRound', 'mapMetadata'])
            ->orderBy('id', 'desc')
            ->findOrFail($id);

        //array map each round
        $demo->rounds = $demo->rounds->map(function ($round) {
            $round->win_reason = $round->meta['reason'] ?? null;
            $round->start_tick = $round->meta['start'] ?? null;
            $round->end_tick = $round->meta['official_end'] ?? null;
            $round->freeze_end_tick = $round->meta['freeze_end'] ?? null;
            return $round;
        });

        return new JsonResponse($demo, JsonResponse::HTTP_OK);
    }

    public function threeD(Request $request, int $id)
    {
        $map = Demo::find($id);
        return Inertia::render('Demo/3D', [
            'weapons' => fn() => $this->imageController->getWeapons()->toArray(),
            'demoId' => $id,
            'demoMap' => $map->map ?? 'de_dust2',
            'name' => $map->name ?? 'Demo',
            'players' => $map->meta['steamPlayers'] ?? [],
        ]);
    }

    public function requestUpload(Request $request)
    {
        $user = $request->user();

        $metadata = [
            'folder_id' => $request->folderId ?? null,
        ];

        $demo = QueuedDemo::create([
            'status' => QueuedDemoStatus::Uploading,
            'owner' => $user->id,
            'name' => str_replace('.dem', '', $request->fileName),
            'metadata' => $metadata,
        ]);

        return response()->json(['demoId' => $demo->id]);
    }

    public function upload(Request $request, int $demoId)
    {
        ini_set('memory_limit', '512M');
        set_time_limit(300);
    
        if (session_id()) {
            session_write_close();
        }
    
        $uploadedFile = $request->file('file');
            \Log::info('Upload debug', [
        'has_file'     => $request->hasFile('file'),
        'file_exists'  => !is_null($uploadedFile),
        'is_valid'     => $uploadedFile?->isValid(),
        'error_code'   => $uploadedFile?->getError(),
        'real_path'    => $uploadedFile?->getRealPath(),
        'size'         => $uploadedFile?->getSize(),
    ]);
        if (!$uploadedFile || !$uploadedFile->isValid()) {
            return response()->json(['error' => 'Invalid file chunk'], 400);
        }
    
        \App\Models\QueuedDemoChunk::insert([
            'queued_demo_id' => $demoId,
            'chunk_index'    => $request->chunkIndex,
            'data'           => file_get_contents($uploadedFile->getRealPath()),
        ]);
    
        return response()->json(['message' => 'Chunk received']);
    }

    public function finalizeUpload(Request $request, int $demoId)
    {
        $user = $request->user();
        $queuedDemo = QueuedDemo::where('id', $demoId)
            ->where('owner', $user->id)
            ->firstOrFail();

        $queuedDemo->status = QueuedDemoStatus::Pending;
        $queuedDemo->save();

        return response()->json(['message' => 'Demo queued for processing']);
    }

    public function adminDemoOverview(Request $request)
    {
        $demos = AdminDemo::where('hide', 0)->orderBy('id', 'asc')->get();

        $qeuedDemos = AdminQueuedDemo::where('status', QueuedDemoStatus::Processing)->get();
        $failedDemos = AdminQueuedDemo::where('status', QueuedDemoStatus::Failed)->get();

        $queuedDemos = array_merge($qeuedDemos->toArray(), $failedDemos->toArray());

        $demos = array_merge($demos->toArray(), $queuedDemos);

        return Inertia::render('Admin/Pages/AdminDemo/Overview', [
            'demos' => $demos,
            'mapicons' => fn() => $this->imageController->getImagesByGroup('mapicon'),
        ]);
    }

    public function adminDemoPath(Request $request)
    {
        $data = AdminDemoPaths::get();
        $maps = $data->pluck('map')->unique();

        $data = $data->mapToGroups(function ($item) {
            return [$item->map => $item];
        })->map(function ($collection) {
            return $collection->first()->toArray();
        })->toArray();


        return Inertia::render('Admin/Pages/AdminDemo/Paths', [
            'pathsData' => $data,
            'mapsList' => $maps,
        ]);
    }

    public function updateDemo(Request $request)
    {
        AdminDemoTactic::updateOrCreate([
            'tactic_id' => $request->tacticId],
            [
            'demo_id' => $request->demoId,
            'round' => $request->roundIndex,
            'map' => $request->map,
        ]);

        return response()->json(['success' => true, 'message' => 'Tactic updated successfully']);
    }

    public function adminRequestUpload(Request $request)
    {
        $demo = AdminQueuedDemo::create([
            'status' => QueuedDemoStatus::Uploading,
            'rounds_to_analyze' => $request->rounds,
            'name' => str_replace('.dem', '', $request->name)
        ]);

        return response()->json(['demoId' => $demo->id]);
    }

    public function adminUploadDemo(Request $request, int $demoId)
    {
        $user = $request->user();

        $request->validate([
            'file' => 'required|file',
            'chunkIndex' => 'required|integer',
            'totalChunks' => 'required|integer'
        ]);

        $queuedDemo = AdminQueuedDemo::where('id', $demoId)->where('status', QueuedDemoStatus::Uploading)->firstOrFail();

        AdminQueuedDemoChunk::create([
            'queued_demo_id' => $demoId,
            'chunk_index' => $request->chunkIndex,
            'data' => file_get_contents($request->file('file')->getRealPath())
        ]);

        $chunkCount = AdminQueuedDemoChunk::where('queued_demo_id', $demoId)->count();

        if ($chunkCount == $request->totalChunks) {
            // All chunks uploaded
            logger("All chunks uploaded for demo $demoId");
            $queuedDemo->status = QueuedDemoStatus::Pending;
            $queuedDemo->save();
        }

        return response()->json(['message' => 'Chunk uploaded successfully']);
    }

    public function demoViewer(Request $request, mixed $id)
    {
        ini_set('memory_limit', '1024M');
        $teams = $request->user()->teams;
        $teamIds = $teams->pluck('id')->toArray();
        
        $demo = $this->secureDemoQuery($teamIds)
            ->with(['rounds' => function ($query) {
                $query->orderBy('round_index', 'asc')
                      ->where('round_index', '>', 0)
                      ->select('meta', 'demo_id', 'round_index');
            }])
            ->orderBy('id', 'desc')
            ->findOrFail($id);

        $demos = $this->getDemos($teams);
        return Inertia::render('Demo/Demo', [
            'demos' => $demos,
            'demoId' => $demo->id,
            'version' => $demo->version ?? 1.0,
            'map' => $demo->map ?? null,
            'rounds' => $demo->rounds ?? [],
            'weapons' => fn() => $this->imageController->getWeapons(),
            'icons' => fn() => $this->imageController->getDemoIcons(),
        ]);
    }

    public function rounds(Request $request, $id) {
        ini_set('memory_limit', '1024M');
        $teams = $request->user()->teams;

        $demo =  $this->secureDemoQuery($teams->pluck('id')->toArray())
            ->with(['rounds' => function ($query) {
                $query->orderBy('round_index', 'asc')->where('round_index', '>', 0)->select('meta', 'demo_id', 'round_index');
            }])
            ->where('id', $id)
            ->orderBy('id', 'desc')
            ->first();

        if (!$demo) {
            return redirect('/demos');
        }

        $demos = $this->getDemos($teams);
        $stats = $demo->stats ?? [];

        return Inertia::render('Demo/Rounds', [
            'demos' => $demos,
            'teamAlpha' => $stats["team1"] ?? [],
            'teamBravo' => $stats["team2"] ?? [],
            'demo' => $demo,
            'demoId' => $id,
            'map' => $demo->map ?? null,
            'rounds' => $demo->rounds ?? [],
            'steamUsers' => $demo["meta"]["steamPlayers"] ?? [],
        ]);
    }

    public function aim(Request $request, $id) {
        $teams = $request->user()->teams;
        $teamIds = $teams->pluck('id')->toArray();

        $demo = $this->secureDemoQuery($teamIds)->findOrFail($id);
        $demos = $this->getDemos($teams);

        return Inertia::render('Demo/Aim', [
            'demoId' => $demo->id,
            'demos' => $demos,
            'stats' => $demo->stats ?? [],
            'map' => $demo->map ?? null,
        ]);
    }

    public function getChunk(Request $request)
    {
        $teamIds = $request->user()->teams->pluck('id')->toArray();
        $demoId = $request->query('demo_id');
        $roundIndex = (int) $request->query('round_index', 0);

        if (!$demoId || $roundIndex < 0) {
            return response()->json(['error' => 'Invalid parameters'], 400);
        }

        $demo = $this->secureDemoQuery($teamIds)
            ->with(['rounds' => function ($query) use ($roundIndex) {
                $query->where('round_index', $roundIndex);
            }])
            ->findOrFail($demoId);

        $rounds = $demo->rounds;
        if (count($rounds) === 0) {
            return response()->json(['error' => 'Rounds not found'], 404);
        }

        return response($rounds[0]->frame_data)
            ->header("Content-Encoding", "gzip")
            ->header("Content-Type", "application/json");
    }

    public function getAdminChunk(Request $request)
    {
        //ini_set('memory_limit', '1024M');

        $demoId = $request->query('demo_id');
        $roundIndex = (int) $request->query('round_index', 0);

        if (!$demoId || $roundIndex < 0) {
            return response()->json(['error' => 'Invalid parameters'], 400);
        }

        $demo = AdminDemo::with(['rounds' => function ($query) use ($roundIndex) {
            $query->where('round_index', $roundIndex);
        }])->where('id', $demoId)->firstOrFail();

        // Get the chunk data
        $rounds = $demo->rounds;
        if (count($rounds) === 0) {
            return response()->json(['error' => 'Rounds not found'], 404);
        }

        $roundData = $rounds[0]; // Assuming chunks are stored as an array in the database
        // Data is gzipped
        return response($roundData->frame_data)->header("Content-Encoding", "gzip")->header("Content-Type", "application/json");
    }

    public function update(Request $request, int $demoId)
    {
        $demo = Demo::where('owner', Auth::id())->findOrFail($demoId);
        
        if ($request->has('demo_name')) {
            $demo->name = $request->demo_name;
        }

        if ($request->has('shared_teams')) {
            $demo->sharedTeams()->sync($request->shared_teams);
        }

        if ($request->has('demo_folder_id')) {
            $folderId = $request->demo_folder_id;

            if ($folderId == 0) {
                $demo->folder()->detach();
            } else {
                $demoFolder = DemoFolder::with('sharedTeams')->findOrFail($folderId);
                $demoFolder->demos()->syncWithoutDetaching([$demoId]);
                $teamIds = $demoFolder->sharedTeams->pluck('id')->toArray();
                $demo->sharedTeams()->sync($teamIds);
            }
        }

        $demo->save();

        return response()->json(['message' => 'Demo shared successfully']);
    }

    public function shareFolder(Request $request, int $folderId)
    {
        $request->validate([
            'teams' => 'array',
            'teams.*' => 'integer|exists:teams,id'
        ]);

        $folder = DemoFolder::where('user_id', Auth::id())->findOrFail($folderId);
        $teamIds = $request->teams;

        // Recursive Sharing: Update folder, subfolders, and all demos within
        $this->syncFolderPermissionsRecursive($folder, $teamIds);

        return response()->json(['message' => 'Folder and all contained demos shared successfully']);
    }

    private function syncFolderPermissionsRecursive(DemoFolder $folder, array $teamIds)
    {
        // 1. Sync the folder itself
        $folder->sharedTeams()->sync($teamIds);

        // 2. Sync all demos associated with this folder
        $folder->demos()->each(function ($demo) use ($teamIds) {
            $demo->sharedTeams()->sync($teamIds);
        });

        // 3. Recurse into child folders
        $folder->children()->each(function ($child) use ($teamIds) {
            $this->syncFolderPermissionsRecursive($child, $teamIds);
        });
    }

    public function destroy(Request $request, int $demoId)
    {
        $user = $request->user();

        $demo = Demo::where('owner', $user->id)->where('id', $demoId)->first();
        if (!$demo) {
            return response()->json(['error' => 'Demo not found'], 418);
        }

        $demo->delete();

        return response()->json(['message' => 'Demo deleted successfully']);
    }

    public function destroyFailed(Request $request, int $demoId)
    {
        $demo = QueuedDemo::where('owner', Auth::id())
            ->where('id', $demoId)
            ->where('status', QueuedDemoStatus::Failed)
            ->first();
        if (!$demo) {
            return response()->json(['error' => 'Demo not found or not failed'], 418);
        }

        $demo->delete();
        return response()->json(['message' => 'Failed demo deleted successfully']);
    }

    /**
     * Update a map
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  string  $map
     * @return \Illuminate\Http\JsonResponse
     */
    public function adminUpdate(Request $request, $map)
    {        
        $adminDemoPath = AdminDemoPaths::where('map', $map)->firstOrFail();

        $adminDemoPath->update([
            'possible_postitions' => $request->possible_postitions,
            'ct' => $request->ct,
            't' => $request->t,
            'position_area_map' => $request->position_area_map,
        ]);

        return response()->json(['success' => true, 'message' => 'Map updated successfully']);
    }

    private function secureDemoQuery($teamIds)
    {
        return Demo::withRoundsCount()->where(function ($query) use ($teamIds) {
            $query->where('owner', Auth::id())
                  ->orWhereHas('sharedTeams', function ($sq) use ($teamIds) {
                      $sq->whereIn('teams.id', $teamIds);
                  });
        });
    }

    private function getDemos($teams, $hideFolderDemos = false)
    {
        $teamIds = $teams->pluck('id')->toArray();

        $q = $this->secureDemoQuery($teamIds)->where('hide', 0);

        if ($hideFolderDemos) {
            $q->whereDoesntHave('folder'); 
        }

        return $q->orderBy('id', 'desc')->get()->map(function ($demo) {
            $allRounds = DemoRound::select('meta')->where('demo_id', $demo->id)->get()->toArray();
            $demo->lastRound = $allRounds ? end($allRounds) : null;
            return $demo;
        });
    }

    public function getDemoInfo(Request $request, int $id)
    {
        $teams = $request->user()->teams;

        // 1. Use the scopeWithRoundsCount() to ensure the count is loaded
        $demos = $this->getDemos($teams);
        $demo = $demos->where('id', $id)->first();

        if (!$demo) {
            return response()->json(['error' => 'Demo not found'], 404);
        }

        return response()->json([
            'id' => $demo->id,
            'name' => $demo->name,
            'map' => $demo->map,
            'rounds' => $demo->rounds_count, 
            'version' => $demo->version,
            'owner' => $demo->owner,
        ]);
    }

    public function getDemoRounds(Request $request, int $id)
    {
        $teams = $request->user()->teams;

        $demos = $this->getDemos($teams);
        $demo = $demos->where('id', $id)->first();
        $demo->rounds = DemoRound::where('demo_id', $id)->orderBy('round_index', 'asc')->select('meta', 'demo_id', 'round_index')->get();

        if (!$demo) {
            return response()->json(['error' => 'Demo not found or access denied'], 404);
        }

        return response()->json($demo->rounds);
    }
}