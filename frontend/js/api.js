// Unico punto di contatto HTTP con il backend (/api/v1).

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || 'Operazione non riuscita.');
    this.status = status;
    this.code = body?.code || 'error';
    this.fieldErrors = body?.field_errors || {};
    this.requestId = body?.request_id;
  }
}

export async function api(method, path, { body, version, idempotencyKey } = {}) {
  const headers = { Accept: 'application/json', 'X-Requested-With': 'insieme' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (version !== undefined) headers['If-Match'] = String(version);
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, { code: 'network', message: 'Connessione non disponibile. Riprova quando sei online.' });
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}
