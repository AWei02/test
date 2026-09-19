import { serviceUrl, getAuthHeaders } from './client';
export async function portalWrite<T = any>(
	path: string,
	method: string,
	body?: unknown,
): Promise<T> {
	const response = await fetch(serviceUrl(path), {
		method,
		headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body),
	});
	const raw = await response.text();
	let result: unknown;
	try {
		result = raw ? JSON.parse(raw) : undefined;
	} catch {
		throw new Error(
			response.ok
				? '服务返回了无法识别的响应。'
				: `服务器请求失败（HTTP ${response.status}），请稍后重试。`,
		);
	}
	if (!response.ok) {
		const detail =
			result && typeof result === 'object' && 'detail' in result
				? (result as { detail?: unknown }).detail
				: undefined;
		throw new Error(typeof detail === 'string' ? detail : '配置格式不正确，请检查输入内容。');
	}
	return result as T;
}
