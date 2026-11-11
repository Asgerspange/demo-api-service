<?php
/**
 * Reference proxy (PHP / Laravel) for the CS Demoviewer "proxy mode" (Stage 04).
 *
 * The viewer points `apiBase` at YOUR backend (e.g. https://customer.com/cs) and sends NO
 * secret. This controller transparently forwards /cs/v1/** to the owner API, injecting the
 * server key + the end-user id server-side, and passes the response (status, body, and the
 * Cache-Control / ETag / Content-Encoding / X-RateLimit-* headers) straight back.
 *
 * Wire it up in routes/web.php (or api.php):
 *
 *     use App\Http\Controllers\CsViewerProxyController;
 *     Route::any('/cs/{path}', CsViewerProxyController::class)->where('path', '.*');
 *
 * Config (config/services.php):
 *     'csviewer' => [
 *         'base'       => env('CSVIEWER_API_BASE', 'https://api.owner.gg'),
 *         'server_key' => env('CSVIEWER_SERVER_KEY'),   // sk_live_… — NEVER sent to the browser
 *     ],
 *
 * Contract: transparent passthrough of /v1/**. The only additions are the two X- headers and
 * TLS. Do not rewrite paths beyond the prefix, do not buffer/transform bodies (binary payloads
 * + gzip must pass through), and preserve caching headers so your CDN/browser can cache them.
 */

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;

class CsViewerProxyController extends Controller
{
    public function __invoke(Request $req, string $path)
    {
        $base = rtrim(config('services.csviewer.base'), '/');

        $resp = Http::withHeaders([
                'X-Server-Key' => config('services.csviewer.server_key'),
                // A STABLE id for the end user, so the owner can apply per-user limits.
                'X-End-User'   => (string) ($req->user()?->id ?? 'anon'),
            ])
            ->withOptions(['stream' => true])           // do not buffer the body
            ->get("{$base}/{$path}", $req->query());

        // Preserve status + all upstream headers (Cache-Control/ETag/Content-Encoding/X-RateLimit-*).
        return response($resp->body(), $resp->status())
            ->withHeaders($resp->headers());
    }
}
