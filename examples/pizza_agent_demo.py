import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Annotated, TypedDict

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from memstate import InMemoryStorage, MemoryStore
from memstate.integrations.langgraph import MemStateCheckpointer

# --- 1. Business Logic (Tools) ---
# Note: These functions don't know anything about LLM. They simply modify data.


@tool
def create_order(pizza_type: str):
    """Start a new pizza order."""
    return {"status": "created", "type": pizza_type, "toppings": []}


@tool
def add_topping(topping: str):
    """Add a topping to the current order."""
    return f"Added {topping}"


@tool
def cancel_order():
    """Cancel the order."""
    return "Order cancelled"


tools = [create_order, add_topping, cancel_order]


# --- 2. State Definition ---


class AgentState(TypedDict):
    # Message history (standard for chat)
    messages: Annotated[list[BaseMessage], add_messages]
    # !!! IMPORTANT: Structured business state!!!
    # LangGraph will store this state, and MemState will persist it in SQL.
    current_order: dict | None


# --- 3. Mock Model ---


class FakeModelWithTools(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


# Dialogue Script:
# 1. User: "I want Pepperoni" -> AI calls create_order
response_1_tool = AIMessage(
    content="", tool_calls=[{"name": "create_order", "args": {"pizza_type": "Pepperoni"}, "id": "call_1"}]
)
# 2. Tool works -> AI confirms
response_1_final = AIMessage(content="I've started a Pepperoni order for you.")

# 3. User: "Add mushrooms" -> AI calls add_topping
response_2_tool = AIMessage(
    content="", tool_calls=[{"name": "add_topping", "args": {"topping": "mushrooms"}, "id": "call_2"}]
)
# 4. Tool works -> AI confirms
response_2_final = AIMessage(content="Added mushrooms to your Pepperoni pizza.")

model = FakeModelWithTools(responses=[response_1_tool, response_1_final, response_2_tool, response_2_final]).bind_tools(
    tools
)


# --- 4. Nodes Logic ---


def agent_node(state: AgentState):
    response = model.invoke(state["messages"])
    return {"messages": [response]}


def tool_node_wrapper(state: AgentState):
    """
    A wrapper around ToolNode.
    Here we intercept the tool's execution result and update the 'current_order' in the state.
    """
    last_msg = state["messages"][-1]
    tool_calls = last_msg.tool_calls

    # First, we make the tools in the standard way
    tool_executor = ToolNode(tools)
    tool_result = tool_executor.invoke(state)

    # NOW THE MAGIC: Updating a structured state based on actions
    new_order_state = state.get("current_order", {}) or {}

    for call in tool_calls:
        if call["name"] == "create_order":
            # Initialize the order
            new_order_state = {"id": 1, "type": call["args"]["pizza_type"], "toppings": [], "status": "active"}
        elif call["name"] == "add_topping":
            # Modifying the order
            if new_order_state:
                new_order_state["toppings"].append(call["args"]["topping"])

    # Return updated messages AND updated business state
    return {"messages": tool_result["messages"], "current_order": new_order_state}


def should_continue(state: AgentState):
    if state["messages"][-1].tool_calls:
        return "tools"
    return END


# --- 5. Assembly and Persistence ---

# Connect MemState
storage = InMemoryStorage()
memory = MemoryStore(storage)
checkpointer = MemStateCheckpointer(memory=memory)

workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node_wrapper)  # Use our smart wrapper

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

app = workflow.compile(checkpointer=checkpointer)

# --- 6. RUN DEMO ---

config = {"configurable": {"thread_id": "user_session_1"}}

print("🍕 Pizza Agent Started (backed by MemState)\n")

# --- STEP 1: Creating an order ---
print(">>> User: I want a Pepperoni pizza.")
# Launch the graph
for update in app.stream({"messages": [HumanMessage(content="I want a Pepperoni pizza.")]}, config=config):
    pass  # Just scroll through the graph

# Get the final state from MemState
state_v1 = app.get_state(config)
print(f"🤖 AI: {state_v1.values['messages'][-1]['content']}")
print(f"📦 DB STATE (Current Order): {state_v1.values.get('current_order')}")
# Expected: type=Pepperoni, toppings=[]


print("\n... (Simulating server restart / user coffee break) ...\n")

# --- STEP 2: Change Order (Context Saved!) ---
print(">>> User: Actually, add mushrooms.")

# LangGraph will automatically load the state from MemState by thread_id
for update in app.stream({"messages": [HumanMessage(content="Actually, add mushrooms.")]}, config=config):
    pass

state_v2 = app.get_state(config)
print(f"🤖 AI: {state_v2.values['messages'][-1]['content']}")
print(f"📦 DB STATE (Current Order): {state_v2.values.get('current_order')}")
# Expected: type=Pepperoni, toppings=['mushrooms']


print("\n--- 🕵️‍♀️ MEMSTATE AUDIT ---")
# Now let's show off its "power": we can view the order change history via SQL.
# LangGraph stores checkpoints.
checkpoints = memory.query(typename="langgraph_checkpoint")
print(f"Total transaction steps saved: {len(checkpoints)}")

# Let's find the moment when the order was created and when it was updated
for cp in checkpoints:
    # Payload in MemState stores the LangGraph checkpoint structure
    order_snapshot = cp["payload"]["checkpoint"]["channel_values"].get("current_order")
    if order_snapshot:
        ts = cp["ts"]
        print(f"🕒 [{ts}] Order State: {order_snapshot}")

print("\n✅ Power Demo: State was persisted, modified transactionally, and is fully auditable via SQL.")
