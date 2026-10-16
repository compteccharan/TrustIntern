const BASE_URL = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message, status, fields = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.fields = fields;
  }
}

export class NetworkError extends Error {
  constructor(message = 'API is not running. Start the backend on port 8000.') {
    super(message);
    this.name = 'NetworkError';
    this.isNetworkError = true;
  }
}

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  let response;
  try {
    response = await fetch(url, options);
  } catch (err) {
    throw new NetworkError('API is not running. Start the backend on port 8000.');
  }

  if (response.status === 422) {
    let errorData = null;
    try {
      errorData = await response.json();
    } catch (_) {
      // ignore json parse error
    }
    const fields = errorData?.fields || {};
    const message = errorData?.message || 'Request validation failed';
    throw new ApiError(message, 422, fields);
  }

  if (!response.ok) {
    let detail = `Server responded with ${response.status}`;
    try {
      const errJson = await response.json();
      detail = errJson.detail || errJson.message || detail;
    } catch (_) {
      // ignore
    }
    throw new ApiError(detail, response.status);
  }

  return response.json();
}

export async function fetchHealth() {
  return request('/api/health');
}

export async function fetchSamples() {
  return request('/api/samples');
}

export async function submitInvestigation(formData) {
  // If formData is plain object, convert to FormData
  let body = formData;
  if (!(formData instanceof FormData)) {
    const fd = new FormData();
    Object.entries(formData).forEach(([key, val]) => {
      if (val !== undefined && val !== null && val !== '') {
        if (typeof val === 'boolean') {
          fd.append(key, val ? 'true' : 'false');
        } else {
          fd.append(key, val);
        }
      }
    });
    body = fd;
  }

  return request('/api/investigations', {
    method: 'POST',
    body,
  });
}

export async function fetchInvestigations() {
  return request('/api/investigations');
}

export async function fetchInvestigationById(id) {
  return request(`/api/investigations/${id}`);
}
