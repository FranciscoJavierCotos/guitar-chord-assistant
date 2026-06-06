"""
ChordCoach LangChain agent — uses native tool calling (function calling API)
instead of text-based ReAct, which is more reliable and uses fewer LLM calls.
"""

import os
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferWindowMemory

from agent.tools import TOOLS

SYSTEM_PROMPT = """You are ChordCoach, an expert guitar teacher and music theorist. You help guitarists learn chord progressions, understand music theory, and discover new songs to play.

Your personality: encouraging, knowledgeable, enthusiastic about music, patient with beginners.

When recommending progressions:
1. Use your tools to fetch real data — do not invent chord names or positions
2. Briefly explain WHY the progression works (the theory behind it)
3. Mention the emotional feel and what genres it suits
4. Suggest a simple practice tip

When the user asks for a progression using a specific chord (e.g. "using Em"), use get_progressions_by_key_tool with that chord's key, or use get_scale_chords to find chords in that key and build a progression.

Response format: Use markdown. When you recommend chords to display, end your message with a JSON block formatted EXACTLY like this so the frontend can render the diagrams:

```json
{{
  "action": "show_chords",
  "chords": ["Em", "C", "G", "D"],
  "progression_name": "Indie Rock Staple",
  "bpm_suggestion": 105
}}
```

If showing a single chord for explanation, use:
```json
{{
  "action": "show_chord",
  "chord": "Am"
}}
```

Keep responses focused, practical, and inspiring."""


def build_agent_executor(memory: ConversationBufferWindowMemory) -> AgentExecutor:
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com/v1",
        temperature=0.7,
        max_tokens=2048,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm=llm, tools=TOOLS, prompt=prompt)

    return AgentExecutor(
        agent=agent,
        tools=TOOLS,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=5,
        early_stopping_method="force",
    )


async def run_agent(
    message: str,
    memory: ConversationBufferWindowMemory,
    context: dict | None = None,
) -> str:
    if context:
        key = context.get("key", "")
        scale = context.get("scale", "")
        if key or scale:
            message = f"[Context: key of {key}, {scale} scale] " + message

    executor = build_agent_executor(memory)
    try:
        result = await executor.ainvoke({"input": message})
        return result.get("output", "I couldn't generate a response. Please try again.")
    except Exception as exc:
        return (
            f"I ran into a technical issue: {exc}\n\n"
            "Please try rephrasing your question or ask me something else!"
        )
