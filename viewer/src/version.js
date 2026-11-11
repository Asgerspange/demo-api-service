// Version pinning, payload negotiation & deprecation (Stage 17 §17.5).
//
// Embedded viewers pin a bundle version and CANNOT be force-updated in the wild, so:
//   - the API keeps serving old `payload_version`s until a published sunset date,
//   - this viewer decodes whatever `payload_version` a demo declares (negotiation),
//   - a host pinned to something near end-of-life gets a console warning.
// `decode.js` currently understands v1; add versions here as the wire format evolves.

export const BUNDLE_VERSION = '0.2.0';

// payload_versions this bundle can decode. A demo declaring something outside this set means the
// embed is too old (or too new) for it → a clear message instead of a broken render.
export const SUPPORTED_PAYLOAD_VERSIONS = [1];

// payload_version → ISO sunset date. The API serves these until the date; the viewer warns hosts
// pinned near end-of-life so they update before it's removed. (Publish the policy: deploy/DEPRECATION.md.)
export const DEPRECATED_PAYLOAD_VERSIONS = {
  // 1: '2027-01-01',  // example: when v2 ships, mark v1 deprecated with its sunset date
};

// Decide whether this bundle can render a demo's payload_version, and whether to warn.
//   returns { ok, warn, message, sunset }
export function negotiatePayloadVersion(payloadVersion, {
  supported = SUPPORTED_PAYLOAD_VERSIONS,
  deprecated = DEPRECATED_PAYLOAD_VERSIONS,
} = {}) {
  const pv = Number(payloadVersion);
  if (!supported.includes(pv)) {
    const newest = Math.max(...supported);
    return {
      ok: false,
      warn: true,
      sunset: null,
      message: pv > newest
        ? `This embed (payload v${supported.join('/')}) is older than this demo (v${pv}). Update the pinned viewer bundle.`
        : `This embed cannot decode payload v${pv} (supports v${supported.join('/')}).`,
    };
  }
  const sunset = deprecated[pv] || null;
  if (sunset) {
    return {
      ok: true, warn: true, sunset,
      message: `payload_version ${pv} is deprecated and served only until ${sunset}; update the pinned viewer bundle (current ${BUNDLE_VERSION}).`,
    };
  }
  return { ok: true, warn: false, sunset: null, message: '' };
}
