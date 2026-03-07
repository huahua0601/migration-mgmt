import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token');
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export const authApi = {
  login: (data) => api.post('/auth/login', data),
  me: () => api.get('/auth/me'),
  changePassword: (data) => api.put('/auth/password', data),
};

export const userApi = {
  list: () => api.get('/users'),
  create: (data) => api.post('/users', data),
  update: (id, data) => api.put(`/users/${id}`, data),
  remove: (id) => api.delete(`/users/${id}`),
};

export const dbApi = {
  list: () => api.get('/db-configs'),
  create: (data) => api.post('/db-configs', data),
  update: (id, data) => api.put(`/db-configs/${id}`, data),
  remove: (id) => api.delete(`/db-configs/${id}`),
  test: (id) => api.post(`/db-configs/${id}/test`),
  testDirect: (data) => api.post('/db-configs/test-connection', data),
  schemas: (id) => api.get(`/db-configs/${id}/schemas`),
};

export const snapshotApi = {
  list: () => api.get('/snapshots'),
  get: (id) => api.get(`/snapshots/${id}`),
  schemas: (id) => api.get(`/snapshots/${id}/schemas`),
  detail: (id, schema) => api.get(`/snapshots/${id}/detail`, { params: schema ? { schema } : {} }),
  upload: (file, name) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('name', name);
    return api.post('/snapshots', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  remove: (id) => api.delete(`/snapshots/${id}`),
};

export const compApi = {
  list: () => api.get('/comparisons'),
  create: (data) => api.post('/comparisons', data),
  get: (id) => api.get(`/comparisons/${id}`),
  results: (id, params) => api.get(`/comparisons/${id}/results`, { params }),
  summary: (id) => api.get(`/comparisons/${id}/summary`),
  remove: (id) => api.delete(`/comparisons/${id}`),
};

export default api;
