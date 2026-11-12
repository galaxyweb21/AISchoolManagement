# EduAI Passkeys and Device Authentication

## Security model

EduAI uses WebAuthn/passkeys for passwordless account authentication. The authenticator (Windows Hello, a phone, a security key, or another supported device) performs local user verification. EduAI stores only the WebAuthn credential ID, public key, signature counter, device label, transport hints, backup/device metadata, and timestamps. It must not collect or store face photographs, face embeddings/templates, fingerprints, or other biometric templates for passkey sign-in.

Windows Hello Face is optional. A compatible Windows Hello infrared (IR) camera is required; an ordinary RGB webcam can work for video calls and still be incompatible with Windows Hello Face. Users can use Windows Hello PIN or a supported fingerprint reader instead. No EduAI camera permission or webcam access is needed for passkey sign-in.

## Register a Windows device

1. Sign in to EduAI and open **Account Settings → Passkeys & Device Security**.
2. Enter a recognizable device name, such as `Office laptop`.
3. Confirm the current EduAI password and select **Register this device**.
4. When the browser displays the passkey prompt, select Windows Hello / this device.
5. Verify with the Windows Hello method configured on the PC (PIN, fingerprint, or Face if supported).
6. Confirm that the new device appears in the registered-device list.

## Register a phone

1. Open EduAI on the computer where the account is signed in.
2. On the passkey page, enter a name such as `Personal phone` and start registration.
3. In the browser's passkey prompt, choose the phone / another-device option when offered.
4. Scan the QR code with the phone and complete the phone's screen-lock or biometric verification prompt.
5. Return to EduAI and confirm the phone passkey is listed.

The browser and phone guide the cross-device flow. Bluetooth may be used for proximity verification; the user should follow the prompts shown by their devices. The phone and computer do not necessarily need to be on the same Wi-Fi network.

## Sign in

On the EduAI login page, select **Sign in with Passkey**. The browser offers an available authenticator. Users may select Windows Hello on the PC, a phone, or a security key. The ordinary username/password form remains available as a fallback.

## Deployment rules

- Local development: use `http://localhost:8000` (or another explicitly configured localhost origin). Do not configure `127.0.0.1` as a WebAuthn RP ID.
- Production: use HTTPS and set `WEBAUTHN_RP_ID` to the exact public hostname and `WEBAUTHN_ORIGIN` to its full HTTPS origin.
- Register passkeys separately on local and production because their RP IDs are different.
- Keep the origin allowlist explicit. Never derive trusted origins or RP IDs from an arbitrary request Host header.
- Keep password login and account recovery available. Encourage users to register more than one passkey/device before relying on passwordless sign-in.
- Do not log credential payloads, private keys, biometric data, or authentication secrets.

## Operational checks

Run in the project's configured Python environment:

```bash
python manage.py check
python manage.py test accounts.tests.test_passkeys
```

Then test actual registration and sign-in in supported browsers with at least one Windows Hello device and one phone. Automated Django tests cannot prove that a physical authenticator or cross-device QR flow works on a specific laptop/phone combination.
