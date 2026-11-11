<?php

namespace App\Services;

use Illuminate\Support\Facades\Cache;
use App\Models\{
    Tactic,
    ProTeam,
    User,
    Demo,
    AdminDemo
};

class CacheService
{
    public function refreshCache()
    {
        $this->refreshTacticsCache();
        $this->refreshProTeamsCache();
        $this->refreshDemosCache();
    }

    public function refreshTacticsCache()
    {
        Cache::forget('tactics');
        return $this->getTactics();
    }

    public function refreshMapsCache()
    {
        Cache::forget('maps');
        return $this->getMaps();
    }

    public function refreshDemosCache()
    {
        Cache::forget('demos');
        return $this->getDemos();
    }

    public function refreshActiveUsersCache()
    {
        Cache::forget('activeUsers');
        return $this->getActiveUsers();
    }

    public function getTactics()
    {
        return Cache::remember('tactics', now()->addDay(), function () {
            $tactics = Tactic::select('id', 'team_name', 'description', 'type', 'tags', 'map', 'side', 'release_date', 'created_at')->orderBy('release_date', 'desc')->get();
            $tactics->load('demo');
            return $tactics;
        });
    }

    public function getActiveUsers()
    {
        return Cache::remember('activeUsers', now()->addDay(), function () {
            return User::whereHas('userInfo', function ($query) {
                $query->where('last_online', '>=', now()->startOfMonth());
            })->count();
        });
    }

    public function refreshProTeamsCache()
    {
        Cache::forget('proTeams');
        return $this->getProTeams();
    }

    public function getProTeams()
    {
        return Cache::remember('proTeams', now()->addDay(), function () {
            $teams = ProTeam::with('players')->get();

            $result = $teams->map(function ($team) {
                $players = $team->players->pluck('name')->all();

                $playerDescriptions = [];
                $playerTimestamps = [];
                $playerLoadouts = [];
            
                foreach ($team->players as $player) {
                    $playerDescriptions[$player->name] = $player->description;
                    $playerTimestamps[$player->name] = $player->timestamp;
                    $playerLoadouts[$player->name] = $player->loadout;
                }

                return [
                    'id' => $team->id,
                    'name' => $team->name,
                    'players' => $players,
                    'player_descriptions' => $playerDescriptions,
                    'player_timestamps' => $playerTimestamps,
                    'player_loadouts' => $playerLoadouts,
                ];
            });

            return $result;
        });
    }

    public function getDemos()
    {
        return Cache::remember('demos', now()->addDay(), function () {
            $userDemos = Demo::withTrashed()->get();
            $adminDemo = AdminDemo::get();
            $demos = $userDemos->merge($adminDemo);
            return count($demos) > 0 ? $demos : collect([]);
        });
    }

    public function getMaps()
    {
        return \App\Models\Map::active()->with('mapMetadata')->get();
    }
}