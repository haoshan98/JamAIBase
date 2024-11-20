from time import time

from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from jamaibase.protocol import (
    ChatCompletionChoice,
    ChatEntry,
    ChatRequest,
    CompletionUsage,
)
from owl.configs.manager import ENV_CONFIG


class ChatCompletionRequest(ChatRequest):
    stream: bool = False


class ChatCompletionChoiceDelta(BaseModel):
    delta: dict[str, str] = Field(description="A chat completion message generated by the model.")
    index: int = Field(description="The index of the choice in the list of choices.")
    finish_reason: str | None = Field(
        default=None,
        description=(
            "The reason the model stopped generating tokens. "
            "This will be stop if the model hit a natural stop point or a provided stop sequence, "
            "length if the maximum number of tokens specified in the request was reached."
        ),
    )


class ChatCompletionResponse(BaseModel):
    id: str = Field(
        description="A unique identifier for the chat completion. Each chunk has the same ID."
    )
    object: str = Field(
        default="chat.completion",
        description="Type of API response object.",
        examples=["chat.completion"],
    )
    created: int = Field(
        default_factory=lambda: int(time()),
        description="The Unix timestamp (in seconds) of when the chat completion was created.",
    )
    model: str = Field(description="The model used for the chat completion.")
    choices: list[ChatCompletionChoice | ChatCompletionChoiceDelta] = Field(
        description="A list of chat completion choices. Can be more than one if `n` is greater than 1."
    )
    usage: CompletionUsage | None = Field(
        description="Number of tokens consumed for the completion request.",
        examples=[CompletionUsage(), None],
    )


app = FastAPI()


@app.post("/v1/chat/completions")
async def chat_completion(body: ChatCompletionRequest):
    output = body.model_dump_json()

    if body.stream:

        async def stream_response():
            for i, char in enumerate(output):
                chunk = ChatCompletionResponse(
                    id=body.id,
                    object="chat.completion.chunk",
                    model=body.model,
                    choices=[
                        ChatCompletionChoiceDelta(
                            index=0,
                            delta=dict(content=char),
                            finish_reason=None if i < len(output) - 1 else "stop",
                        )
                    ],
                    usage=CompletionUsage(
                        prompt_tokens=len(output),
                        completion_tokens=i + 1,
                        total_tokens=len(output) + i + 1,
                    ),
                )
                yield f"data: {chunk.model_dump()}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_response(), media_type="text/event-stream")

    return ChatCompletionResponse(
        id=body.id,
        model=body.model,
        choices=[
            ChatCompletionChoice(
                index=0, message=ChatEntry.assistant(output), finish_reason="stop"
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=len(output),
            completion_tokens=len(output),
            total_tokens=len(output) + len(output),
        ),
    )


@app.get("/health", tags=["Health"])
async def health() -> Response:
    """Health check."""
    return Response(status_code=200)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "owl.entrypoints.chat_echo:app",
        reload=False,
        host=ENV_CONFIG.owl_host,
        port=6868,
        workers=1,
        limit_concurrency=10,
    )
