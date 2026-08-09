from server.tools.tool_executor import execute_tool, register_tool
from server.tools.tool_result import ToolResult
from server.tools.tool_definitions import TOOL_DECLARATIONS

# Import all tool modules to trigger their @register_tool registrations
import server.tools.app_launcher
import server.tools.media_control
import server.tools.notifications
import server.tools.browser_tools
import server.tools.system_tools
import server.tools.service_tools
import server.tools.finance_tools
