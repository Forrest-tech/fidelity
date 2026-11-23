import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * "I'm not a robot": the check people know from other sites — tick the box, it spins for a moment, a green
 * tick appears. Used on sign-in, sign-up and first-run setup.
 *
 * Behind the box is a proof-of-work (ALTCHA, MIT): the server issues a signed challenge, the browser solves
 * it when the box is ticked and sends the proof with the form. Unlike reCAPTCHA or Turnstile there is no
 * third party, no tracking cookie and no outside call, so it also works on the office network without
 * internet. The key derivation uses @noble/hashes instead of WebCrypto, because WebCrypto only exists on
 * HTTPS pages and Fidelity is often opened as http://<server-address>. A proof works once and for 10 minutes:
 * after a failed attempt, or when it has expired, the box is cleared and must be ticked again.
 */
export interface CaptchaHandle {
  reset: () => void;
  focus: () => void;
}

type Phase = "idle" | "solving" | "ready" | "failed" | "expired";

interface Challenge {
  parameters: { algorithm: string; nonce: string; salt: string; cost: number; keyLength?: number; keyPrefix: string; expiresAt?: number };
  signature?: string;
}

const VALID_MS = 9 * 60_000;            // the server accepts a proof for 10 minutes

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

export const Captcha = forwardRef<CaptchaHandle, { onChange: (payload: string | null) => void; invalid?: boolean }>(function Captcha({ onChange, invalid }, ref) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>("idle");
  const run = useRef<AbortController | null>(null);
  const expiry = useRef<number | undefined>(undefined);
  const box = useRef<HTMLDivElement>(null);

  const clear = useCallback((next: Phase) => {
    run.current?.abort();
    window.clearTimeout(expiry.current);
    setPhase(next);
    onChange(null);
  }, [onChange]);

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
        window.clearTimeout(expiry.current);
        expiry.current = window.setTimeout(() => clear("expired"), VALID_MS);
      },
      () => {
        if (!ac.signal.aborted) clear("failed");
      },
    );
  }, [onChange, clear]);

  useEffect(() => () => {
    run.current?.abort();
    window.clearTimeout(expiry.current);
  }, []);

  useImperativeHandle(ref, () => ({ reset: () => clear("idle"), focus: () => box.current?.focus() }), [clear]);

  const tick = () => {
    if (phase === "idle" || phase === "failed" || phase === "expired") start();
  };
  const checked = phase === "ready" ? true : phase === "solving" ? "mixed" : false;
  const note = phase === "failed" ? t("login.captchaFailed") : phase === "expired" ? t("login.captchaExpiredTick") : "";
  return (
    <div className={`fx-human fx-human-${phase}${invalid && phase !== "ready" ? " fx-human-invalid" : ""}`}>
      <div className="fx-human-row">
        <div
          ref={box}
          role="checkbox"
          tabIndex={0}
          aria-checked={checked}
          aria-label={t("login.notRobot")}
          aria-describedby={note ? "fx-human-note" : undefined}
          aria-invalid={invalid && phase !== "ready" ? true : undefined}
          className="fx-human-box"
          onClick={tick}
          onKeyDown={(e) => {
            if (e.key === " " || e.key === "Enter") {
              e.preventDefault();
              tick();
            }
          }}
        >
          {phase === "solving" ? <span className="fx-human-spin" aria-hidden="true" /> : phase === "ready" ? <span className="fx-human-tick" aria-hidden="true">✓</span> : null}
        </div>
        <span className="fx-human-label" onClick={tick} aria-hidden="true">
          {phase === "solving" ? t("login.verifying") : t("login.notRobot")}
        </span>
        <span className="fx-human-brand" aria-hidden="true">
          <b>Fidelity</b>
          <small>{t("login.noTracking")}</small>
        </span>
      </div>
      <div className="sr-only" role="status" aria-live="polite" aria-label={t("login.captchaGroup")}>
        {phase === "ready" ? t("login.captchaReady") : phase === "solving" ? t("login.verifying") : note}
      </div>
      {note && <div id="fx-human-note" className="fx-human-note">{note}</div>}
    </div>
  );
});
