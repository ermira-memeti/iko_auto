"""Optional local generation. No answer quality or grounding claims are made."""
ABSTAIN_MESSAGE = "The provided documents do not establish an answer."


def format_context(hits, max_chars_per_hit: int = 2000) -> str:
    return "\n\n".join(
        f"[Source {i}: {hit.chunk.source_path}"
        + (f", PDF page {hit.chunk.page}" if hit.chunk.page else "")
        + f", chunk {hit.chunk.chunk_id}]\n{hit.chunk.text[:max_chars_per_hit]}"
        for i, hit in enumerate(hits, start=1)
    )


def evidence_preview(hits) -> str:
    """Return only an excerpt, never an inferred policy answer."""
    if not hits:
        return ABSTAIN_MESSAGE
    hit = hits[0]
    return f"Evidence excerpt from {hit.chunk.source_path}:\n{hit.chunk.text}"


def load_local_llm(model_name: str = "google/flan-t5-small"):
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise RuntimeError("Local generation needs requirements-ml.txt (transformers).") from exc
    return pipeline("text2text-generation", model=model_name, device=-1)


def answer_with_context(question: str, context: str, generator=None, max_new_tokens: int = 160) -> str:
    if not context.strip():
        return ABSTAIN_MESSAGE
    if generator is None:
        return "No generative model selected. Review the retrieved evidence above."
    prompt = (
        "Use ONLY the supplied insurance policy excerpts to answer the question. "
        "If evidence is insufficient, say 'Insufficient evidence'. Cite the source labels. "
        "Do not invent coverage.\n\n"
        f"CONTEXT:\n{context}\n\nQUESTION: {question}\nANSWER:"
    )
    output = generator(prompt, max_new_tokens=max_new_tokens, do_sample=False)
    return output[0].get("generated_text", "").strip() or ABSTAIN_MESSAGE
