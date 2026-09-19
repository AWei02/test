import express from 'express';
import cors from 'cors';
import http from 'http';

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
// Same-origin streaming gateway to the Python service. Python enforces access.
app.use('/api/service', (req, res) => {
	const upstream = http.request(
		{
			hostname: '127.0.0.1',
			port: 8000,
			path: req.url,
			method: req.method,
			headers: { ...req.headers, host: '127.0.0.1:8000' },
		},
		(response) => {
			res.writeHead(response.statusCode ?? 502, response.headers);
			response.pipe(res);
		},
	);
	upstream.on('error', () => {
		if (!res.headersSent)
			res.status(502).json({ detail: 'AgentScope 服务未连接，请启动 python main.py。' });
		else res.end();
	});
	res.on('close', () => upstream.destroy());
	req.pipe(upstream);
});

app.get('/api/health', (_req, res) => {
	res.json({ status: 'ok' });
});

app.listen(PORT, () => {
	console.log(`Server running on http://localhost:${PORT}`);
});
