import io
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from strategy_agent.mcp import MCPServer, serve, PROTOCOL_VERSION
from strategy_agent.state import Project


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.server = MCPServer(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def initialize(self):
        return self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})

    def test_handshake_discovery_and_call(self):
        self.assertEqual(self.initialize()["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        tools = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertTrue(any(t["name"] == "search_evidence" for t in tools))
        result = self.server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_materials", "arguments": {}}})
        self.assertFalse(result["result"]["isError"])
        self.assertEqual(json.loads(result["result"]["content"][0]["text"])["materials"], [])

    def test_unknown_tool_protocol_error_and_bad_arguments_tool_error(self):
        self.initialize()
        missing = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "shell"}})
        self.assertEqual(missing["error"]["code"], -32602)
        bad = self.server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ingest_document", "arguments": {}}})
        self.assertTrue(bad["result"]["isError"])

    def test_stdio_parse_failure_is_protocol_not_stdout_log(self):
        output = io.StringIO()
        serve(Path(self.temporary.name), io.StringIO('not-json\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'), output)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1]["result"], {})

    def test_batch_supported_and_initialize_not_batched(self):
        batch = self.server.handle([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notification"}])
        self.assertEqual(len(batch), 1)
        forbidden = self.server.handle([{"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSION}}])
        self.assertEqual(forbidden[0]["error"]["code"], -32600)

    def test_tools_need_initialization(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(response["error"]["code"], -32002)

    def test_human_question_survives_new_process(self):
        project = Project(self.temporary.name)
        project.initialize("Исследовать снижение повторного использования")
        self.initialize()
        response = self.server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "request_human", "arguments": {"question": "Какое событие считать повторным использованием?"}}})
        self.assertFalse(response["result"]["isError"])
        output = json.loads(response["result"]["content"][0]["text"])
        self.assertTrue(output["checkpoint_saved"])
        raw = subprocess.check_output([sys.executable, "-c", "import json,sys; print(json.dumps(json.load(open(sys.argv[1],encoding='utf-8'))))", str(project.state_file)], text=True)
        state = json.loads(raw)
        self.assertEqual(state["status"], "needs_input")
        self.assertEqual(state["question"], "Какое событие считать повторным использованием?")
        self.assertEqual(project.read("state/messages.json")[-1]["role"], "assistant")

    def test_question_without_project_init_reports_error(self):
        self.initialize()
        response = self.server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "request_human", "arguments": {"question": "Какова цель?"}}})
        self.assertTrue(response["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
