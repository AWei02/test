/** UUIDs for message IDs, including LAN HTTP where randomUUID is unavailable. */
function fallbackRandomUUID(): ReturnType<Crypto['randomUUID']> {
	// getRandomValues is also available in non-secure browser contexts.
	const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
	bytes[6] = (bytes[6] & 0x0f) | 0x40;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;
	const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function createMessageId(): string {
	return typeof globalThis.crypto.randomUUID === 'function'
		? globalThis.crypto.randomUUID()
		: fallbackRandomUUID();
}

/** The AgentScope SDK also generates IDs internally, so cover it before React starts. */
export function installRandomUUIDCompatibility(): void {
	if (typeof globalThis.crypto.randomUUID !== 'function') {
		Object.defineProperty(globalThis.crypto, 'randomUUID', {
			value: fallbackRandomUUID,
			configurable: true,
			writable: true,
		});
	}
}
