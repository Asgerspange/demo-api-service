<?php

namespace App\Http\Controllers;

use App\Services\CacheService;
use Illuminate\Http\JsonResponse;


class MapController extends Controller
{
    public function __construct(
        private readonly CacheService $cacheService
    ) {}

    public function index()
    {
        return new JsonResponse($this->cacheService->getMaps(), JsonResponse::HTTP_OK);
    }

    public function show(int $id)
    {
        $maps = $this->cacheService->getMaps();
        $map = collect($maps)->firstWhere('id', $id);

        if (!$map) {
            return new JsonResponse(['message' => 'Map not found'], JsonResponse::HTTP_NOT_FOUND);
        }
         
        return new JsonResponse($map, JsonResponse::HTTP_OK);
    }
}
