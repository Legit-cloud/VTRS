import * as Crypto from "expo-crypto";
import { Directory, File, Paths } from "expo-file-system";
import { fetch as expoFetch } from "expo/fetch";
import * as ImageManipulator from "expo-image-manipulator";
import type { FileUploader } from "../core/sync";
import type { PhotoDraft } from "../core/capture";

const MAX_BYTES = 8 * 1024 * 1024;
const hex = (buffer: ArrayBuffer) =>
  Array.from(new Uint8Array(buffer), (b) => b.toString(16).padStart(2, "0")).join("");

/**
 * Turn what the camera produced into the file that will be sent: resized so a low-end phone and
 * a thin network cope, kept in app storage (camera cache files are temporary), and hashed. The
 * hash is of exactly these bytes, which is what the server checks after upload.
 */
export async function preparePhoto(cameraUri: string): Promise<PhotoDraft> {
  const longest = 2200;
  const resized = await ImageManipulator.manipulateAsync(
    cameraUri,
    [{ resize: { width: longest } }],
    { compress: 0.8, format: ImageManipulator.SaveFormat.JPEG },
  );
  const folder = new Directory(Paths.document, "sheets");
  folder.create({ idempotent: true, intermediates: true });
  const target = new File(folder, `${Crypto.randomUUID()}.jpg`);
  new File(resized.uri).copy(target);

  const bytes = await target.bytes();
  if (bytes.byteLength > MAX_BYTES) {
    throw new Error("The photo is too large to send. Move closer to the sheet and try again.");
  }
  const sha256 = hex(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes));
  return {
    uri: target.uri,
    mime: "image/jpeg",
    size: bytes.byteLength,
    sha256,
    width: resized.width,
    height: resized.height,
  };
}

export const fileUploader: FileUploader = {
  async put(uri, url, headers, mime) {
    const file = new File(uri);
    const response = await expoFetch(url, {
      method: "PUT",
      headers: { "Content-Type": mime, ...headers },
      body: file,
    });
    return { status: response.status };
  },
};
