import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Bot protection on the sign-in and first-run forms: an invisible ALTCHA proof-of-work check.
 *
 * The server issues a signed ALTCHA challenge (Python `altcha` library); the browser solves it with the
 * ALTCHA solver (`altcha/lib`) and sends the proof with the form. Nothing to click, no third party, no
 * tracking. The key derivation uses @noble/hashes (audited, pure JavaScript) instead of WebCrypto,
 * because WebCrypto only exists on HTTPS pages and Fidelity is often opened as http://<server-address>
 * on the office network (the ALTCHA widget refuses to run there). A proof works once: the form calls
 * `reset()` after each attempt.
 */
export interface CaptchaHandle {
  reset: () => void;
}

type Phase = "solving" | "ready" | "failed";

interface Challenge {
  parameters: { algorithm: string; nonce: string; salt: string; cost: number; keyLength?: number; keyPrefix: string; expiresAt?: number };
  signature?: string;
}

async function solveOnce(signal: AbortSignal): Promise<string> {
  const res = await fetch("/api/v1/auth/challenge", { credentials: "same-origin", signal, cache: "no-store" });
  if (!res.ok) throw new Error(`challenge ${res.status}`);
  const challenge = (await res.json()) as Challenge;
  const [{ solveChallenge }, { pbkdf2 }, { sha256 }] = await Promise.all([
    import("altcha/lib"),
    import("@noble/hashes/pbkdf2.js"),
    import("@noble/hashes/sha2.js"),
  ]);
  const controller = new AbortController();
  signal.addEventListener("abort", () => controller.abort());
  const solution = await solveChallenge({
    challenge: challenge as never,
    controller,
    timeout: 60_000,
    deriveKey: async (p: { cost: number; keyLength?: number }, salt: Uint8Array, password: Uint8Array) => ({
      derivedKey: pbkdf2(sha256, password, salt, { c: p.cost, dkLen: p.keyLength ?? 32 }),
    }),
  } as never);
  if (!solution) throw new Error("not solved");
  return btoa(JSON.stringify({ challenge, solution }));
}

export const Captcha = forwardRef<CaptchaHandle, { onChange: (payload: string | null) => void }>(function Captcha({ onChange }, ref) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>("solving");
  const run = useRef<AbortController | null>(null);

  const start = useCallback(() => {
    run.current?.abort();
    const ac = new AbortController();
    run.current = ac;
    setPhase("solving");
    onChange(null);
    solveOnce(ac.signal).then(
      (p) => {
        if (ac.signal.aborted) return;
        setPhase("ready");
        onChange(p);
      },
      () => {
        if (ac.signal.aborted) return;
        setPhase("failed");
        onChange(null);
      },
    );
  }, [onChange]);

  useEffect(() => {
    start();
    // a proof expires after 10 minutes: renew it before then if the page is left open
    const renew = window.setInterval(start, 8 * 60_000);
    return () => {
      window.clearInterval(renew);
      run.current?.abort();
    };
  }, [start]);

  useImperativeHandle(ref, () => ({ reset: start }), [start]);

  return (
    <div className={`fx-captcha fx-captcha-${phase}`} role="status" aria-live="polite" aria-label={t("login.captchaGroup")}>
      <span className="fx-captcha-dot" aria-hidden="true" />
      <span>{phase === "ready" ? t("login.captchaReady") : phase === "failed" ? t("login.captchaFailed") : t("login.captchaChecking")}</span>
      {phase === "failed" && (
        <button type="button" className="fx-a" onClick={start}>
          {t("state.retry")}
        </button>
      )}
    </div>
  );
});
