# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities privately via GitHub's
**Security → Report a vulnerability** tab. Do NOT open public issues.

## Threat Model

Artifact Deck runs untrusted AI-generated HTML/JS/React code in a sandbox.

### Network Isolation (Defense in Depth)
1. **CSP**: `connect-src 'none'`, `img-src data: blob:`, `frame-src 'none'`
2. **WebKit Policy**: All resource responses to non-local URIs blocked at RESPONSE level
3. **Flatpak**: No `--share=network` permission (OS-level block)
4. **Invalid Origin**: Each artifact uses unique `.invalid` domain

### Permission Denial
- Camera, microphone, geolocation, notifications: universally denied
- File access from file URLs: disabled
- Modal dialogs and auto-opened windows: blocked
- WebRTC and media streams: disabled

### Storage Isolation
- Per-artifact isolated directories under `state/{id}/`
- Unique invalid origin prevents cross-artifact localStorage access
- Custom `window.storage` API scoped to individual artifacts

### Known Limitations
- `unsafe-inline`/`unsafe-eval` required for Babel transpilation
- Hostile JS can still consume local CPU/memory
- Not a VM substitute for high-risk scenarios
