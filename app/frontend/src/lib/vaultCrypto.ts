// Криптография сейфа (ТЗ §16.2) — вся логика Web Crypto API в одном месте.
// PBKDF2 (300 000 итераций, OWASP-рекомендация 2023) → AES-GCM. Ключ
// создаётся с extractable: false — сырые байты никогда не появляются в
// JS-читаемой памяти, только через crypto.subtle.*. Отдельный случайный
// IV на каждое шифрование — переиспользовать IV с одним ключом в GCM
// нельзя, это реальная крипто-уязвимость, а не перестраховка.

const PBKDF2_ITERATIONS = 300_000;
const VERIFIER_MARKER = "notenotes-vault-v1";

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

// Явный ArrayBuffer, а не ArrayBufferLike (TS lib.dom различает их для
// BufferSource с TS 5.7+, new Uint8Array(n) выводится как generic
// Uint8Array<ArrayBufferLike> и не проходит без этого в crypto.subtle.*).
function base64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(b64);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function generateSalt(): string {
  return bytesToBase64(crypto.getRandomValues(new Uint8Array(16)));
}

export async function deriveKey(password: string, saltB64: string): Promise<CryptoKey> {
  const passwordKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: base64ToBytes(saltB64), iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    passwordKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export interface EncryptedField {
  iv: string;
  ciphertext: string;
}

export async function encryptBytes(key: CryptoKey, data: ArrayBuffer): Promise<EncryptedField> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data);
  return { iv: bytesToBase64(iv), ciphertext: bytesToBase64(new Uint8Array(ciphertext)) };
}

export async function decryptBytes(key: CryptoKey, field: EncryptedField): Promise<ArrayBuffer> {
  return crypto.subtle.decrypt(
    { name: "AES-GCM", iv: base64ToBytes(field.iv) },
    key,
    base64ToBytes(field.ciphertext),
  );
}

export async function encryptField(key: CryptoKey, plaintext: string): Promise<EncryptedField> {
  return encryptBytes(key, new TextEncoder().encode(plaintext).buffer as ArrayBuffer);
}

export async function decryptField(key: CryptoKey, field: EncryptedField): Promise<string> {
  return new TextDecoder().decode(await decryptBytes(key, field));
}

// Файлы — отдельный путь от encryptField/decryptField: тот кодирует IV и
// ciphertext раздельно в base64 (удобно для JSON), но для файла в сотни МБ
// это ~33% лишней памяти на саму строку плюс ещё раз столько же при
// сборке Blob из неё. Вместо этого IV (12 байт, не секрет) просто
// приклеивается ПЕРЕД шифротекстом в одном бинарном Blob — весь объект
// самодостаточен, расшифровке не нужно ничего, кроме самого файла и ключа.
export async function encryptFileBlob(
  key: CryptoKey,
  data: ArrayBuffer,
  type: string = "application/octet-stream",
): Promise<Blob> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data);
  return new Blob([iv, ciphertext], { type });
}

export async function decryptFileBytes(key: CryptoKey, data: ArrayBuffer): Promise<ArrayBuffer> {
  const iv = data.slice(0, 12);
  const ciphertext = data.slice(12);
  return crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
}

// Пароль сейфа никогда не проверяется сервером (честный zero-knowledge для
// этого секрета) — verifier шифрует известную строку-маркер тем же ключом;
// при разблокировке GCM сам ловит подделку/неверный пароль через ошибку
// расшифровки тега аутентичности, не тихий мусор на выходе.
export async function createVerifier(key: CryptoKey): Promise<EncryptedField> {
  return encryptField(key, VERIFIER_MARKER);
}

export async function checkVerifier(key: CryptoKey, verifier: EncryptedField): Promise<boolean> {
  try {
    return (await decryptField(key, verifier)) === VERIFIER_MARKER;
  } catch {
    return false;
  }
}
