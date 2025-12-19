import asyncio
import json
import time
from typing import Dict, Set, Optional
from dataclasses import dataclass, field, asdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from contextlib import asynccontextmanager

# ========================
# Global State
# ========================

@dataclass
class ClientSession:
    """Represents a connected bot client"""
    client_id: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    status: str = "INACTIVE"
    bot_id: str = "NONE"
    variables: Dict[str, str] = field(default_factory=lambda: {
        "BOT_ID": "NONE",
        "TICKET_TEXT": "NONE",
        "TICKET_CODE": "NONE",
        "TICKET_URL": "NONE",
        "ACCOUNT_EMAIL": "NONE",
        "ACCOUNT_PASSWORD": "NONE"
    })
    last_seen: float = field(default_factory=time.time)
    logs: list = field(default_factory=list)
    
    def to_dict(self):
        """Convert to dict for JSON serialization"""
        return {
            "client_id": self.client_id,
            "status": self.status,
            "bot_id": self.bot_id,
            "variables": self.variables,
            "last_seen": self.last_seen,
            "logs": self.logs[-50:]  # Last 50 logs only
        }


class ServerState:
    """Global server state"""
    def __init__(self):
        self.clients: Dict[str, ClientSession] = {}
        self.ticket_code_map: Dict[str, str] = {}  # ticket_text -> code
        self.server_status: str = "INACTIVE"
        self.websocket_clients: Set[WebSocket] = set()
        self.lock = asyncio.Lock()
        self._client_counter = 0
    
    def get_next_client_id(self) -> str:
        self._client_counter += 1
        return f"CLIENT_{self._client_counter}"
    
    async def broadcast_to_ui(self, message: dict):
        """Send update to all connected web UI clients"""
        dead_sockets = set()
        for ws in self.websocket_clients:
            try:
                await ws.send_json(message)
            except:
                dead_sockets.add(ws)
        self.websocket_clients -= dead_sockets


state = ServerState()

# ========================
# Protocol Functions
# ========================

def pack_message(msg: str) -> bytes:
    """Pack message to exactly 1024 bytes"""
    msg_bytes = msg.encode('utf-8')
    if len(msg_bytes) > 1024:
        msg_bytes = msg_bytes[:1024]
    return msg_bytes.ljust(1024, b'\0')


def unpack_message(data: bytes) -> str:
    """Unpack 1024-byte message"""
    return data.rstrip(b'\0').decode('utf-8', errors='ignore')


def parse_message(msg: str) -> tuple:
    """Parse message into parts: (msg_code, payload_parts)"""
    parts = msg.split('/')
    if len(parts) > 0:
        return parts[0], parts[1:]
    return "", []


# ========================
# TCP Client Handler
# ========================

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle individual client connection"""
    addr = writer.get_extra_info('peername')
    client_id = state.get_next_client_id()
    
    print(f"[{client_id}] New connection from {addr}")
    
    # Create client session
    session = ClientSession(
        client_id=client_id,
        reader=reader,
        writer=writer
    )
    
    async with state.lock:
        state.clients[client_id] = session
    
    # Notify UI
    await state.broadcast_to_ui({
        "event": "client_connected",
        "client": session.to_dict()
    })
    
    try:
        while True:
            # Read exactly 1024 bytes
            data = await reader.readexactly(1024)
            if not data:
                break
            
            session.last_seen = time.time()
            msg = unpack_message(data)
            
            if not msg:
                continue
            
            # Parse and handle message
            await handle_client_message(session, msg)
            
    except asyncio.IncompleteReadError:
        print(f"[{client_id}] Connection closed")
    except Exception as e:
        print(f"[{client_id}] Error: {e}")
    finally:
        # Cleanup
        async with state.lock:
            if client_id in state.clients:
                del state.clients[client_id]
        
        writer.close()
        await writer.wait_closed()
        
        # Notify UI
        await state.broadcast_to_ui({
            "event": "client_disconnected",
            "client_id": client_id
        })
        
        print(f"[{client_id}] Disconnected")


async def handle_client_message(session: ClientSession, msg: str):
    """Process incoming message from client"""
    msg_code, payload = parse_message(msg)
    
    print(f"[{session.client_id}] Received: {msg_code}")
    
    if msg_code == "CLIENT_STATUS_RESPONSE":
        if payload:
            session.status = payload[0]
            await state.broadcast_to_ui({
                "event": "client_updated",
                "client": session.to_dict()
            })
    
    elif msg_code == "CHECK_VARIABLE_REQUEST":
        # Client requesting a variable value
        if payload:
            var_name = payload[0]
            
            # Special handling for TICKET_CODE
            if var_name == "TICKET_CODE":
                ticket_text = session.variables.get("TICKET_TEXT", "NONE")
                value = state.ticket_code_map.get(ticket_text, "NONE")
            else:
                value = session.variables.get(var_name, "NONE")
            
            response = f"CHECK_VARIABLE_RESPONSE/{value}"
            await send_to_client(session, response)
    
    elif msg_code == "CHANGE_VARIABLE_RESPONSE":
        # Client confirmed variable change
        if payload:
            result = payload[0]
            print(f"[{session.client_id}] Variable change: {result}")
    
    elif msg_code == "REPORT_CLIENT_ERROR":
        # Client reporting an error
        if payload:
            error_msg = "/".join(payload)
            session.logs.append(f"ERROR: {error_msg}")
            await state.broadcast_to_ui({
                "event": "client_log",
                "client_id": session.client_id,
                "log": f"ERROR: {error_msg}"
            })
    
    elif msg_code == "REPORT_CLIENT_FINISH":
        # Client finished task
        if payload:
            result = payload[0]
            session.logs.append(f"FINISHED: {result}")
            await state.broadcast_to_ui({
                "event": "client_log",
                "client_id": session.client_id,
                "log": f"FINISHED: {result}"
            })
    
    elif msg_code == "LOG_CLIENT_EVENT" or msg_code == "CLIENT_LOG_EVENT":
        # Client logging an event
        if payload:
            log_msg = "/".join(payload)
            session.logs.append(log_msg)
            await state.broadcast_to_ui({
                "event": "client_log",
                "client_id": session.client_id,
                "log": log_msg
            })


async def send_to_client(session: ClientSession, msg: str):
    """Send message to client"""
    try:
        packed = pack_message(msg)
        session.writer.write(packed)
        await session.writer.drain()
        print(f"[{session.client_id}] Sent: {msg}")
    except Exception as e:
        print(f"[{session.client_id}] Send error: {e}")


# ========================
# TCP Server
# ========================

async def start_tcp_server():
    """Start the TCP server for bot clients"""
    server = await asyncio.start_server(
        handle_client,
        '0.0.0.0',
        9999
    )
    
    addr = server.sockets[0].getsockname()
    print(f'TCP Server listening on {addr}')
    
    async with server:
        await server.serve_forever()


# ========================
# Web Server (FastAPI)
# ========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start TCP server in background
    tcp_task = asyncio.create_task(start_tcp_server())
    yield
    # Shutdown: cancel TCP server
    tcp_task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serve the dashboard HTML"""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Server Dashboard</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f5f6fa;
            margin: 0;
            padding: 0;
        }
        header {
            background: #162447;
            color: white;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        header h1 {
            margin: 0;
            font-size: 28px;
        }
        .status-badge {
            background: #32cd74;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 14px;
        }
        .status-badge.inactive {
            background: #e74c3c;
        }
        .container {
            display: flex;
            gap: 30px;
            padding: 30px;
        }
        .panel {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .left-panel {
            width: 65%;
        }
        .right-panel {
            width: 35%;
        }
        h2 {
            margin-top: 0;
            font-size: 22px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        table th, table td {
            padding: 10px;
            border-bottom: 1px solid #ddd;
            text-align: left;
        }
        .status-active {
            background: #32cd74;
            color: white;
            padding: 3px 10px;
            border-radius: 5px;
            font-size: 12px;
        }
        .status-waiting {
            background: #f0a500;
            color: white;
            padding: 3px 10px;
            border-radius: 5px;
            font-size: 12px;
        }
        button {
            background: #162447;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            margin-right: 10px;
            margin-bottom: 10px;
        }
        button:hover {
            background: #1f4068;
        }
        input, select {
            width: 100%;
            padding: 8px;
            margin-bottom: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        .section {
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #eee;
        }
        .section:last-child {
            border-bottom: none;
        }
        .log-area {
            background: #f8f9fa;
            padding: 10px;
            border-radius: 4px;
            max-height: 200px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
        }
        .log-entry {
            padding: 2px 0;
        }
    </style>
</head>
<body>
    <header>
        <h1>🤖 Bot Management Server</h1>
        <span class="status-badge" id="serverStatus">INACTIVE</span>
    </header>

    <div class="container">
        <div class="left-panel panel">
            <h2>Connected Clients (<span id="clientCount">0</span>)</h2>
            <button onclick="selectAll()">Select All</button>
            <table>
                <thead>
                    <tr>
                        <th>Select</th>
                        <th>Client ID</th>
                        <th>Status</th>
                        <th>Bot ID</th>
                        <th>Ticket Type</th>
                        <th>Email</th>
                    </tr>
                </thead>
                <tbody id="clientTable">
                    <tr>
                        <td colspan="6" style="text-align: center; color: #999;">No clients connected</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="right-panel panel">
            <div class="section">
                <h2>Server Control</h2>
                <button onclick="toggleServer()">Toggle Server Status</button>
            </div>

            <div class="section">
                <h2>Commands</h2>
                <button onclick="sendCommand('login')">Send Login</button>
                <button onclick="sendCommand('buy')">Buy Tickets</button>
            </div>

            <div class="section">
                <h2>Edit Variables</h2>
                <label>Variable Name:</label>
                <select id="varName">
                    <option value="TICKET_TEXT">Ticket Text</option>
                    <option value="TICKET_URL">Ticket URL</option>
                    <option value="ACCOUNT_EMAIL">Account Email</option>
                    <option value="ACCOUNT_PASSWORD">Account Password</option>
                    <option value="BOT_ID">Bot ID</option>
                </select>
                <label>New Value:</label>
                <input type="text" id="varValue" placeholder="Enter new value" />
                <button onclick="applyVariable()">Apply to Selected</button>
            </div>

            <div class="section">
                <h2>Ticket Code Manager</h2>
                <div id="ticketCodes">
                    <p style="color: #999;">No ticket codes defined</p>
                </div>
                <label>Ticket Text:</label>
                <input type="text" id="ticketText" placeholder="e.g., VIP" />
                <label>Code:</label>
                <input type="text" id="ticketCode" placeholder="e.g., CODE123" />
                <button onclick="setTicketCode()">Save Ticket Code</button>
            </div>

            <div class="section">
                <h2>Activity Log</h2>
                <div class="log-area" id="logArea"></div>
            </div>
        </div>
    </div>

    <script>
        let ws;
        let selectedClients = new Set();

        function connectWebSocket() {
            ws = new WebSocket(`ws://${window.location.host}/ws`);
            
            ws.onopen = () => {
                console.log('WebSocket connected');
                addLog('Connected to server');
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleServerMessage(data);
            };
            
            ws.onclose = () => {
                console.log('WebSocket disconnected');
                addLog('Disconnected from server');
                setTimeout(connectWebSocket, 3000);
            };
        }

        function handleServerMessage(data) {
            if (data.event === 'client_connected' || data.event === 'client_updated') {
                updateClientTable();
            } else if (data.event === 'client_disconnected') {
                updateClientTable();
            } else if (data.event === 'client_log') {
                addLog(`[${data.client_id}] ${data.log}`);
            } else if (data.event === 'ticket_map_changed') {
                updateTicketCodes(data.ticket_map);
            } else if (data.event === 'clients_list') {
                renderClients(data.clients);
            } else if (data.event === 'server_status') {
                updateServerStatus(data.status);
            }
        }

        function updateServerStatus(status) {
            const badge = document.getElementById('serverStatus');
            badge.textContent = status;
            badge.className = 'status-badge ' + (status === 'ACTIVE' ? '' : 'inactive');
        }

        function renderClients(clients) {
            const tbody = document.getElementById('clientTable');
            document.getElementById('clientCount').textContent = clients.length;
            
            if (clients.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #999;">No clients connected</td></tr>';
                return;
            }
            
            tbody.innerHTML = clients.map(client => `
                <tr>
                    <td><input type="checkbox" onchange="toggleClient('${client.client_id}')" ${selectedClients.has(client.client_id) ? 'checked' : ''} /></td>
                    <td>${client.client_id}</td>
                    <td><span class="status-waiting">${client.status}</span></td>
                    <td>${client.bot_id}</td>
                    <td>${client.variables.TICKET_TEXT}</td>
                    <td>${client.variables.ACCOUNT_EMAIL}</td>
                </tr>
            `).join('');
        }

        function updateClientTable() {
            ws.send(JSON.stringify({ action: 'list_clients' }));
        }

        function toggleClient(clientId) {
            if (selectedClients.has(clientId)) {
                selectedClients.delete(clientId);
            } else {
                selectedClients.add(clientId);
            }
        }

        function selectAll() {
            ws.send(JSON.stringify({ action: 'list_clients' }));
            setTimeout(() => {
                const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(cb => {
                    cb.checked = true;
                    const clientId = cb.onchange.toString().match(/'([^']+)'/)[1];
                    selectedClients.add(clientId);
                });
            }, 100);
        }

        function toggleServer() {
            ws.send(JSON.stringify({ action: 'toggle_server' }));
        }

        function sendCommand(cmd) {
            if (selectedClients.size === 0) {
                alert('Please select at least one client');
                return;
            }
            ws.send(JSON.stringify({
                action: cmd === 'login' ? 'send_login' : 'send_buy',
                clients: Array.from(selectedClients)
            }));
            addLog(`Sent ${cmd} command to ${selectedClients.size} clients`);
        }

        function applyVariable() {
            if (selectedClients.size === 0) {
                alert('Please select at least one client');
                return;
            }
            const varName = document.getElementById('varName').value;
            const varValue = document.getElementById('varValue').value;
            
            ws.send(JSON.stringify({
                action: 'apply_variable',
                clients: Array.from(selectedClients),
                variable: varName,
                value: varValue
            }));
            addLog(`Applied ${varName}=${varValue} to ${selectedClients.size} clients`);
            document.getElementById('varValue').value = '';
        }

        function setTicketCode() {
            const ticketText = document.getElementById('ticketText').value;
            const ticketCode = document.getElementById('ticketCode').value;
            
            if (!ticketText || !ticketCode) {
                alert('Please enter both ticket text and code');
                return;
            }
            
            ws.send(JSON.stringify({
                action: 'set_ticket_code',
                ticket_text: ticketText,
                code: ticketCode
            }));
            addLog(`Set code for ${ticketText}: ${ticketCode}`);
            document.getElementById('ticketText').value = '';
            document.getElementById('ticketCode').value = '';
        }

        function updateTicketCodes(ticketMap) {
            const container = document.getElementById('ticketCodes');
            if (Object.keys(ticketMap).length === 0) {
                container.innerHTML = '<p style="color: #999;">No ticket codes defined</p>';
                return;
            }
            
            container.innerHTML = Object.entries(ticketMap).map(([text, code]) => `
                <div style="background: #f8f9fa; padding: 8px; margin-bottom: 5px; border-radius: 4px;">
                    <strong>${text}</strong>: ${code}
                </div>
            `).join('');
        }

        function addLog(message) {
            const logArea = document.getElementById('logArea');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
            logArea.appendChild(entry);
            logArea.scrollTop = logArea.scrollHeight;
        }

        connectWebSocket();
        setInterval(updateClientTable, 2000);
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for UI updates"""
    await websocket.accept()
    state.websocket_clients.add(websocket)
    
    # Send initial state
    await websocket.send_json({
        "event": "server_status",
        "status": state.server_status
    })
    
    await websocket.send_json({
        "event": "clients_list",
        "clients": [client.to_dict() for client in state.clients.values()]
    })
    
    await websocket.send_json({
        "event": "ticket_map_changed",
        "ticket_map": state.ticket_code_map
    })
    
    try:
        while True:
            data = await websocket.receive_json()
            await handle_ui_command(data, websocket)
    except WebSocketDisconnect:
        state.websocket_clients.remove(websocket)


async def handle_ui_command(data: dict, websocket: WebSocket):
    """Handle commands from the web UI"""
    action = data.get("action")
    
    if action == "list_clients":
        await websocket.send_json({
            "event": "clients_list",
            "clients": [client.to_dict() for client in state.clients.values()]
        })
    
    elif action == "toggle_server":
        state.server_status = "ACTIVE" if state.server_status == "INACTIVE" else "INACTIVE"
        await state.broadcast_to_ui({
            "event": "server_status",
            "status": state.server_status
        })
    
    elif action == "apply_variable":
        client_ids = data.get("clients", [])
        var_name = data.get("variable")
        var_value = data.get("value")
        
        for client_id in client_ids:
            if client_id in state.clients:
                session = state.clients[client_id]
                session.variables[var_name] = var_value
                
                # Send CHANGE_VARIABLE_REQUEST to client
                msg = f"CHANGE_VARIABLE_REQUEST/{var_name}/{var_value}"
                await send_to_client(session, msg)
        
        await state.broadcast_to_ui({
            "event": "clients_list",
            "clients": [client.to_dict() for client in state.clients.values()]
        })
    
    elif action == "send_login":
        client_ids = data.get("clients", [])
        for client_id in client_ids:
            if client_id in state.clients:
                session = state.clients[client_id]
                await send_to_client(session, "CLIENT_LOGIN")
    
    elif action == "send_buy":
        client_ids = data.get("clients", [])
        for client_id in client_ids:
            if client_id in state.clients:
                session = state.clients[client_id]
                await send_to_client(session, "CLIENT_BUY_TICKET")
    
    elif action == "set_ticket_code":
        ticket_text = data.get("ticket_text")
        code = data.get("code")
        
        if ticket_text and code:
            state.ticket_code_map[ticket_text] = code
            await state.broadcast_to_ui({
                "event": "ticket_map_changed",
                "ticket_map": state.ticket_code_map
            })


# ========================
# Main Entry Point
# ========================

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 Starting Bot Management Server")
    print("=" * 50)
    print("TCP Server: 0.0.0.0:9999")
    print("Web UI: http://localhost:8000")
    print("=" * 50)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)