import asyncio
import os
import tempfile
import subprocess
from pathlib import Path
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters
from google.adk.models.lite_llm import LiteLlm  # Use LiteLLM for additional flexibility
from dotenv import load_dotenv

# Import our Pydantic schema fixer
from .pydantic_schema_fix import process_mcp_tools

# Load environment variables from the root .env file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

async def clone_alphavantage_repo():
    """Clone the Alpha Vantage repository to a temporary directory."""
    temp_dir = tempfile.mkdtemp()
    print(f"--- Cloning Alpha Vantage MCP server to {temp_dir} ---")
    
    try:
        process = await asyncio.create_subprocess_exec(
            'git', 'clone', 'https://github.com/calvernaz/alphavantage.git', temp_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            print("--- Successfully cloned Alpha Vantage repository ---")
            return temp_dir
        else:
            print(f"--- Failed to clone repository: {stderr.decode()} ---")
            return None
    except Exception as e:
        print(f"--- Error cloning repository: {e} ---")
        return None

class MCPToolProxy:
    """A proxy class to wrap MCP tools and fix their schemas."""
    
    def __init__(self, original_tool):
        self.original_tool = original_tool
        # Copy attributes from the original tool
        self.name = original_tool.name
        self.description = original_tool.description
        # Fix the input schema
        if hasattr(original_tool, "inputSchema") and original_tool.inputSchema:
            from .pydantic_schema_fix import fix_schema_with_pydantic
            self.inputSchema = fix_schema_with_pydantic(original_tool.inputSchema)
        else:
            self.inputSchema = original_tool.inputSchema
    
    async def __call__(self, *args, **kwargs):
        """Delegate the call to the original tool."""
        return await self.original_tool(*args, **kwargs)

async def get_tools_async():
    """Connects to the Alpha Vantage MCP server and returns the tools and exit stack."""
    print("--- Attempting to start and connect to Alpha Vantage MCP server ---")
    
    # Clone the repository to get the server code
    repo_dir = await clone_alphavantage_repo()
    if not repo_dir:
        print("--- Failed to clone the repository, cannot connect to MCP server ---")
        class DummyExitStack:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        return [], DummyExitStack()
    
    try:
        # Connect to the MCP server using the recommended configuration
        tools, exit_stack = await MCPToolset.from_server(
            connection_params=StdioServerParameters(
                command='uv',
                args=['--directory', repo_dir, 'run', 'alphavantage'],
                env={'ALPHAVANTAGE_API_KEY': os.environ.get('ALPHA_VANTAGE_API_KEY', '')}
            )
        )
        
        print(f"--- Successfully connected to Alpha Vantage MCP server. Discovered {len(tools)} tool(s). ---")
        # Print discovered tool names for debugging/instruction refinement
        for tool in tools:
            print(f"  - Discovered tool: {tool.name}")
        
        # Process the tools to fix schema issues with Gemini
        print("--- Processing tool schemas to make compatible with Gemini ---")
        fixed_tools = [MCPToolProxy(tool) for tool in tools]
        
        return fixed_tools, exit_stack
    
    except FileNotFoundError:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! ERROR: 'uv' command not found. Please install uv using: pip install uv !!!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        # Return empty tools and a no-op exit stack to prevent agent failure
        class DummyExitStack:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        return [], DummyExitStack()
    
    except Exception as e:
        print(f"--- ERROR connecting to or starting Alpha Vantage MCP server: {e} ---")
        # Return empty tools and a no-op exit stack
        class DummyExitStack:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        return [], DummyExitStack()

async def create_agent():
    """Creates the agent instance after fetching tools from the MCP server."""
    tools, exit_stack = await get_tools_async()
    
    if not tools:
        print("--- WARNING: No tools discovered from MCP server. Agent will lack stock data functionality. ---")
    
    # Use a different model from the Gemini family if needed
    # Alternatively, we could use LiteLLM to access different models
    # llm = LiteLlm(model="google/gemini-1.5-pro-latest")
    
    agent_instance = Agent(
        name="stock_data_agent",
        description="A financial data agent that fetches stock market data using Alpha Vantage API.",
        model="gemini-2.0-flash",  # Try a different model variant if needed
        instruction=(
            "You are the Stock Data Agent. Your task is to fetch financial data from Alpha Vantage using the connected MCP tools."
            "\n1. **Identify Stock Symbol:** Determine which stock symbol the user wants information about (e.g., 'AAPL', 'GOOGL')."
            "\n2. **Call Discovered Tools:** You **MUST** look for and use the tools discovered from the Alpha Vantage MCP server."
            "\n3. **Present Results:** Format the returned data in a clear, readable format for the user."
            "\n   - Present prices, changes, and other metrics in a structured way."
            "\n   - Clearly state which stock symbol the information is for."
            "\n   - If the tool returns an error message, relay that message accurately."
            "\n4. **Handle Missing Tool:** If you cannot find the required tools, inform the user that you cannot fetch stock data due to a configuration issue."
            "\n5. **Do Not Hallucinate:** Only provide information returned by the tools."
        ),
        tools=tools,
    )
    
    return agent_instance, exit_stack

root_agent = create_agent()