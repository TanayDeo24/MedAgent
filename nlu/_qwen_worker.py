#!/usr/bin/env python
"""Standalone worker process for local Qwen2.5-1.5B-Instruct inference.

Launched via `subprocess.Popen([sys.executable, __file__], ...)` from
`nlu/local_qwen_extractor.py` - deliberately a plain script invocation, NOT
`multiprocessing` with the "spawn" start method, because spawn needs to
pickle/unpickle the target function by importing its module, which for a
function living inside the `nlu` package would re-trigger `nlu`'s own
import chain (nlu -> agent.prompts -> agent/__init__.py -> agent.graph ->
agent.nodes -> eager RAG/FAISS load) INSIDE the child too - defeating the
whole point of isolating Qwen from FAISS's native thread pool (see
`nlu/local_qwen_extractor.py`'s module docstring for the reproduced
segfault this avoids). A plain script process only ever imports the
stdlib + torch/transformers named below - never anything under
`agent`/`nlu`.

Protocol: one JSON object per line on stdin, one JSON object per line on
stdout, flushed after every line (no batching, no buffering surprises).
  stdin:  {"cmd": "generate", "prompt": "...", "max_new_tokens": 700}
          {"cmd": "stop"}
  stdout: {"type": "ready", "device": "mps"|"cpu"}      (once, at startup)
          {"type": "result", "text": "...", "usage": {...}}
          {"type": "error", "error": "..."}
"""

import json
import sys


def main():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_id = "Qwen/Qwen2.5-1.5B-Instruct"
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.float32)
    model.to(device)
    model.eval()

    sys.stdout.write(json.dumps({"type": "ready", "device": device}) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if msg.get("cmd") == "stop":
            break

        if msg.get("cmd") != "generate":
            continue

        prompt = msg["prompt"]
        max_new_tokens = msg.get("max_new_tokens", 700)
        try:
            messages = [{"role": "user", "content": prompt}]
            chat_text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer([chat_text], return_tensors="pt").to(device)
            input_len = inputs["input_ids"].shape[1]
            with torch.no_grad():
                output_ids = model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )
            gen_ids = output_ids[0][input_len:]
            out_text = tokenizer.decode(gen_ids, skip_special_tokens=True)
            usage = {
                "input_tokens": int(input_len),
                "output_tokens": int(gen_ids.shape[0]),
                "total_tokens": int(input_len + gen_ids.shape[0]),
            }
            sys.stdout.write(json.dumps({"type": "result", "text": out_text, "usage": usage}) + "\n")
        except Exception as e:
            sys.stdout.write(json.dumps({"type": "error", "error": f"{type(e).__name__}: {e}"}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
