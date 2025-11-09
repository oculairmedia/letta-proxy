# Letta Proxy

Webhook proxy and context poller services for Letta agents with Graphiti integration.

## Services

### Letta Webhook Proxy (`proxy/`)

Node.js/TypeScript service that proxies webhooks from Letta agents to downstream services.

**Features:**
- Webhook forwarding with configurable endpoints
- Support for agent tagging (e.g., `graphiti` tag)
- Shared state management with poller service
- Debug logging support

### Letta Context Poller (`poller/`)

Python service that polls Letta API for agent information and manages context.

**Features:**
- Periodic polling of Letta agents
- Integration with Graphiti knowledge graph
- BookStack knowledge base integration
- Persistent state management

## Quick Start

### Using Docker Compose

```bash
# Clone the repository
git clone https://github.com/oculairmedia/letta-proxy.git
cd letta-proxy

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env

# Start services
docker-compose up -d
```

### Using Pre-built Images

Images are automatically built and published to GitHub Container Registry on every commit:

```bash
docker pull ghcr.io/oculairmedia/letta-webhook-proxy:latest
docker pull ghcr.io/oculairmedia/letta-context-poller:latest
```

## Configuration

### Environment Variables

Create a `.env` file with the following variables:

```bash
# Letta Configuration
LETTA_BASE_URL=https://letta2.oculair.ca
LETTA_PASSWORD=your-letta-password
LETTA_API_URL=http://192.168.50.90:8283
LETTA_DISABLE_INITIAL_HISTORY_PULL=true

# Graphiti Configuration
GRAPHITI_ENDPOINT=http://192.168.50.90:8003

# BookStack Configuration (optional)
BS_URL=https://knowledge.oculair.ca
BS_TOKEN_ID=your-token-id
BS_TOKEN_SECRET=your-token-secret

# OpenAI Configuration
OPENAI_API_KEY=your-openai-key

# Webhook Configuration
WEBHOOK_URL=http://192.168.50.90:5005/webhook

# Debug Settings
DEBUG=true
NODE_ENV=development
```

## Development

### Proxy Service

```bash
cd proxy
npm install
npm run build
npm start
```

### Poller Service

```bash
cd poller
pip install -r requirements.txt
python list_letta_agents.py
```

## Building Docker Images

### Build Both Images

```bash
docker-compose build
```

### Build Individually

```bash
# Proxy
docker build -t oculair/letta-webhook-proxy:latest ./proxy

# Poller
docker build -t oculair/letta-context-poller:latest ./poller
```

## CI/CD

GitHub Actions automatically builds and publishes Docker images on every push to `main`:

- **GHCR**: `ghcr.io/oculairmedia/letta-webhook-proxy:latest` and `ghcr.io/oculairmedia/letta-context-poller:latest`

No additional secrets required - uses the automatic `GITHUB_TOKEN` for authentication.

## Architecture

```
┌─────────────────┐
│  Letta Agents   │
└────────┬────────┘
         │ webhooks
         ▼
┌─────────────────┐      ┌──────────────────┐
│  Webhook Proxy  │◄────►│  Context Poller  │
│   (Node.js)     │      │    (Python)      │
└────────┬────────┘      └────────┬─────────┘
         │                         │
         │ forward                 │ poll & sync
         ▼                         ▼
┌─────────────────┐      ┌──────────────────┐
│   Downstream    │      │  Letta API +     │
│    Services     │      │  Graphiti        │
└─────────────────┘      └──────────────────┘
```

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Support

For issues and questions, please open an issue on GitHub.
