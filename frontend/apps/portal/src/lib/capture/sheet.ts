import { ApiError, uuid7, type EvidenceMime } from "@vtrs/core";
import { ep } from "@/lib/api";
import { withRetry, type RetryHooks } from "./retry";

/** The server's limit per file. */
export const MAX_BYTES = 8 * 1024 * 1024;
const TARGET_BYTES = 2 * 1024 * 1024;
const LONGEST_SIDE = 2200;
const QUALITIES = [0.85, 0.78, 0.7, 0.62, 0.55];

export interface PreparedSheet {
  blob: Blob;
  mime: EvidenceMime;
  sha256: string;
  /** For the preview and the "compressed from" note. */
  originalBytes: number;
}

const ACCEPTED: readonly string[] = ["image/jpeg", "image/png", "image/webp", "application/pdf"];

/**
 * Make the file that is uploaded. Photos are scaled so the longest side is about 2,200 px and
 * re-encoded as JPEG, stepping the quality down until the file is about 2 MB, which keeps a
 * result sheet legible. PDFs are sent as they are. The hash is of the exact bytes uploaded.
 */
export async function prepareSheet(file: File): Promise<PreparedSheet> {
  const type = file.type || (file.name.toLowerCase().endsWith(".pdf") ? "application/pdf" : "");
  if (type === "application/pdf") {
    if (file.size > MAX_BYTES) throw tooBig();
    return { blob: file, mime: "application/pdf", sha256: await sha256(file), originalBytes: file.size };
  }
  if (!type.startsWith("image/")) {
    throw new ApiError({
      status: 400,
      code: "unsupported_file",
      detail: "Choose a photo or a PDF of the result sheet.",
    });
  }
  const blob = await compress(file).catch(() => null);
  // A format the browser cannot draw (some phones' HEIC) goes up as it is if the server takes it.
  if (!blob) {
    if (!ACCEPTED.includes(type)) {
      throw new ApiError({
        status: 400,
        code: "unsupported_file",
        detail: "This photo format cannot be read. Take the photo again, or choose a JPEG or PDF.",
      });
    }
    if (file.size > MAX_BYTES) throw tooBig();
    return { blob: file, mime: type as EvidenceMime, sha256: await sha256(file), originalBytes: file.size };
  }
  if (blob.size > MAX_BYTES) throw tooBig();
  return { blob, mime: "image/jpeg", sha256: await sha256(blob), originalBytes: file.size };
}

async function compress(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, LONGEST_SIDE / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("no canvas");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(bitmap, 0, 0, width, height);
  bitmap.close?.();
  let out: Blob | null = null;
  for (const quality of QUALITIES) {
    out = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
    if (out && out.size <= TARGET_BYTES) break;
  }
  if (!out) throw new Error("encode failed");
  return out;
}

export async function sha256(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

const tooBig = () =>
  new ApiError({
    status: 400,
    code: "file_too_large",
    detail: "This file is larger than 8 MB. Take a new photo, or send a smaller PDF.",
  });

/**
 * Request a presigned upload for the sheet, put the bytes straight to storage, then confirm.
 * Each step retries on its own with backoff; an expired upload link is asked for again.
 */
export async function uploadSheet(
  versionId: string,
  sheet: PreparedSheet,
  hooks: RetryHooks & { onStage?: (stage: "requesting" | "uploading" | "confirming") => void } = {},
): Promise<{ evidenceId: string; completion: string }> {
  const evidenceId = uuid7();
  for (let round = 0; ; round++) {
    hooks.onStage?.("requesting");
    const entry = await withRetry(
      () =>
        ep.evidence.requestUpload({
          evidence_id: evidenceId,
          version_id: versionId,
          kind: "EC8A",
          mime: sheet.mime,
          size: sheet.blob.size,
          sha256: sheet.sha256,
        }),
      hooks,
    );
    if (entry.upload) {
      hooks.onStage?.("uploading");
      const put = await withRetry(async () => {
        const headers = { ...(entry.upload!.headers as Record<string, string>) };
        // The browser sets the length itself and refuses a script that tries.
        delete headers["Content-Length"];
        let response: Response;
        try {
          response = await fetch(entry.upload!.url, {
            method: entry.upload!.method || "PUT",
            headers,
            body: sheet.blob,
          });
        } catch (cause) {
          throw new ApiError({ status: 0, code: "network", detail: String(cause) });
        }
        if (response.status >= 500 || response.status === 429) {
          throw new ApiError({ status: response.status, code: "storage", detail: "Storage busy." });
        }
        return response;
      }, hooks);
      // A link that expired while the phone was offline: ask for a fresh one, once.
      if (put.status === 403 && round === 0) continue;
      if (!put.ok) {
        throw new ApiError({
          status: put.status,
          code: "upload_refused",
          detail: `The upload was refused (${put.status}). Try choosing the file again.`,
        });
      }
    }
    hooks.onStage?.("confirming");
    const state = await withRetry(() => ep.evidence.complete(evidenceId), hooks);
    return { evidenceId, completion: state.completion };
  }
}
