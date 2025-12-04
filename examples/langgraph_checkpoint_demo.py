import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from memstate import InMemoryStorage, MemoryStore
from memstate.integrations.langgraph import MemStateCheckpointer

storage = InMemoryStorage()
memory = MemoryStore(storage)
checkpointer = MemStateCheckpointer(memory=memory)


# --- 1. Create Fake Model with bind tools ---


class FakeModelWithTools(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


# --- 2. Agent Setup (Fake Model) ---


@tool
def get_weather(city: str):
    """Get the weather for a city."""
    if "sf" in city.lower() or "san francisco" in city.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


tools = [get_weather]

# --- THE MAGIC IS HERE ---
# We pre-program the model's responses.
# LangGraph runs in a loop: Model -> Tool -> Model -> End
# We need 2 responses for the first run and 1 response for the second.

# Scenario for Run 1:
# 1. The model decides to call the tool (returns tool_calls)
response_1_call_tool = AIMessage(
    content="", tool_calls=[{"name": "get_weather", "args": {"city": "SF"}, "id": "call_123"}]
)
# 2. After executing the tool, the model receives the result and gives an answer
response_1_final = AIMessage(content="The weather in SF is 60 degrees and foggy.")

# Scenario for Run 2 (Memory Test):
# 1. The model answers a question about NY using context (simulate this)
response_2_final = AIMessage(content="Yes, usually 90 degrees in NY is hotter than 60 in SF.")

model = FakeModelWithTools(responses=[response_1_call_tool, response_1_final, response_2_final]).bind_tools(tools)

# -------------------


def call_model(state: MessagesState):
    response = model.invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state: MessagesState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END


# Building a graph
workflow = StateGraph(MessagesState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

# Connect our checkpointer
app = workflow.compile(checkpointer=checkpointer)


# --- 3. Launch ---

thread_config = {"configurable": {"thread_id": "session_1"}}

print("\n--- Run 1: Asking about weather (Triggering Tool) ---")
# User asks about the weather
result = app.invoke({"messages": [("user", "What's the weather in SF?")]}, config=thread_config)
print("AI:", result["messages"][-1].content)


print("\n--- Run 2: Continuing context (Memory Test) ---")
# We continue the same thread.
result_2 = app.invoke({"messages": [("user", "Is it hotter there than in NY?")]}, config=thread_config)
print("AI:", result_2["messages"][-1].content)


print("\n--- Audit ---")
checkpoints = memory.query(typename="langgraph_checkpoint")
print(f"Total checkpoints stored: {len(checkpoints)}")

if len(checkpoints) > 0:
    last_cp = checkpoints[-1]
    print(f"Latest checkpoint ID: {last_cp['payload']['thread_ts']}")
    print("✅ Demo finished successfully!")
