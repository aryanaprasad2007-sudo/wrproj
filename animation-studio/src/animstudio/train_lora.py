"""Train a character LoRA from a handful of your own reference images.

    py -m animstudio.train_lora --character characters/mira --steps 1200

Why this fits in 8 GB when "SDXL LoRA training needs 12-16 GB" is the usual
advice: the VAE and both text encoders are used ONCE, up front, and then
deleted. Their outputs are cached to disk, and the training loop only ever
holds the unet plus the LoRA adapters.

    naive:  unet 5.0 + text encoders 1.4 + VAE 0.3 + grads/optimiser  -> OOM
    cached: unet 5.0 + LoRA grads 0.1 + optimiser 0.2                 -> ~6.5 GB

The cost is that caching freezes the captions and the crops -- no random crop
augmentation, no caption dropout that varies per epoch. For a 15-30 image
character set that is the right trade: the dataset is too small for
augmentation to matter more than fitting on the card does.

DATASET ADVICE, which matters more than any hyperparameter here:
  * 15-30 images. Fewer than 10 overfits to the background; more than ~40 stops
    helping on a single character.
  * Vary pose, expression, angle and framing. A LoRA trained on six turnaround
    poses reproduces those six poses forever -- the most common failure, and it
    looks like "the model ignores my prompt".
  * Vary or remove the background. A constant background gets learned as part
    of the character.
  * Caption what VARIES (pose, angle, clothing state), not what is constant.
    Anything you caption becomes editable; anything you leave uncaptioned gets
    absorbed into the trigger token, which is what you want for identity.
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import pathlib
import sys

log = logging.getLogger(__name__)

_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _images(refs_dir: pathlib.Path):
    return sorted(p for p in refs_dir.iterdir() if p.suffix.lower() in _IMG_EXT)


def _caption_for(img: pathlib.Path, trigger: str, description: str) -> str:
    """Sidecar .txt wins; otherwise trigger + description.

    A per-image caption file lets you say "side view, arms raised" for one
    shot, which is exactly the variation that stops pose memorisation.
    """
    side = img.with_suffix(".txt")
    if side.exists():
        text = side.read_text(encoding="utf-8").strip()
        return f"{trigger}, {text}" if trigger and trigger not in text else text
    return ", ".join(x for x in (trigger, description) if x)


def _prepare_image(path, size: int):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    # Centre crop to square then resize. Turnarounds are usually already
    # centred; a smart crop would risk cutting the face on close-ups.
    s = min(im.size)
    left, top = (im.width - s) // 2, (im.height - s) // 2
    return im.crop((left, top, left + s, top + s)).resize((size, size), Image.LANCZOS)


def cache_conditioning(pipe, images, captions, size, device, dtype, cache_dir, is_sdxl):
    """Encode every image to a latent and every caption to embeddings, once."""
    import torch
    cache_dir.mkdir(parents=True, exist_ok=True)
    records = []

    log.info("caching %d latents + embeddings at %dpx ...", len(images), size)
    pipe.vae.to(device)
    with torch.no_grad():
        for i, (img, cap) in enumerate(zip(images, captions)):
            arr = _prepare_image(img, size)
            import numpy as np
            t = torch.from_numpy(np.asarray(arr, dtype="float32") / 127.5 - 1.0)
            t = t.permute(2, 0, 1).unsqueeze(0).to(device, dtype=pipe.vae.dtype)
            lat = pipe.vae.encode(t).latent_dist.sample() * pipe.vae.config.scaling_factor
            rec = {"latent": lat.squeeze(0).cpu(), "caption": cap, "source": str(img)}
            records.append(rec)
    pipe.vae.to("cpu")
    del pipe.vae

    encoders = [pipe.text_encoder] + ([pipe.text_encoder_2] if is_sdxl else [])
    tokenizers = [pipe.tokenizer] + ([pipe.tokenizer_2] if is_sdxl else [])
    for e in encoders:
        e.to(device)

    with torch.no_grad():
        for rec in records:
            if is_sdxl:
                # SDXL concatenates the penultimate hidden state of both
                # encoders, and takes the pooled output from encoder 2 only.
                embs, pooled = [], None
                for tok, enc in zip(tokenizers, encoders):
                    ids = tok(rec["caption"], padding="max_length", truncation=True,
                              max_length=tok.model_max_length, return_tensors="pt").input_ids.to(device)
                    out = enc(ids, output_hidden_states=True)
                    pooled = out[0]
                    embs.append(out.hidden_states[-2])
                rec["prompt_embeds"] = torch.cat(embs, dim=-1).squeeze(0).cpu()
                rec["pooled"] = pooled.squeeze(0).cpu()
            else:
                ids = tokenizers[0](rec["caption"], padding="max_length", truncation=True,
                                    max_length=tokenizers[0].model_max_length,
                                    return_tensors="pt").input_ids.to(device)
                rec["prompt_embeds"] = encoders[0](ids)[0].squeeze(0).cpu()

    for e in encoders:
        e.to("cpu")
    if is_sdxl:
        del pipe.text_encoder, pipe.text_encoder_2
    else:
        del pipe.text_encoder

    from . import hardware
    hardware.free_vram()
    log.info("cached. text encoders and VAE released.")
    return records


def train(args):
    import torch
    import torch.nn.functional as F
    from diffusers import (StableDiffusionXLPipeline, StableDiffusionPipeline,
                           DDPMScheduler)
    from diffusers.training_utils import cast_training_params
    from peft import LoraConfig
    from . import config as cfgmod, hardware, progress

    progress.setup_logging(args.verbose)
    hw = hardware.detect()
    if not hw.cuda:
        log.error("no CUDA device -- LoRA training on CPU is not practical "
                  "(days, not hours). See README 'Install'.")
        return 1

    char_dir = pathlib.Path(args.character)
    from .characters import Character
    char = Character.load(char_dir)
    refs = char_dir / "refs"
    if not refs.is_dir() or not _images(refs):
        log.error("no reference images in %s", refs)
        return 1
    images = _images(refs)
    if len(images) < 8:
        log.warning("only %d reference images -- expect the LoRA to overfit to "
                    "the background and pose. 15-30 is the useful range.", len(images))

    project = cfgmod.ProjectConfig.load(
        args.project or (char_dir.parents[1] / "config" / "project.yaml")
    )
    is_sdxl = project.base_kind == "sdxl"
    size = args.resolution or (768 if is_sdxl else 512)
    device, dtype = "cuda", torch.float16

    ckpt = pathlib.Path(project.base_checkpoint)
    cls = StableDiffusionXLPipeline if is_sdxl else StableDiffusionPipeline
    log.info("loading base for training: %s", ckpt)
    pipe = (cls.from_single_file(str(ckpt), torch_dtype=dtype)
            if ckpt.suffix == ".safetensors" and ckpt.exists()
            else cls.from_pretrained(project.base_checkpoint, torch_dtype=dtype))

    captions = [_caption_for(p, char.trigger, char.description) for p in images]
    log.info("trigger token: '%s'", char.trigger or "(none -- set one!)")
    records = cache_conditioning(pipe, images, captions, size, device, dtype,
                                 char_dir / ".cache", is_sdxl)

    unet = pipe.unet
    unet.requires_grad_(False)
    unet.to(device, dtype=dtype)
    # Gradient checkpointing recomputes activations in the backward pass:
    # ~30% slower, and the difference between fitting and not fitting here.
    unet.enable_gradient_checkpointing()

    # rank 16 / alpha 16 is the sweet spot for a single character: rank 4 loses
    # fine detail (eye shape, accessory geometry), rank 64 memorises the
    # background and triples file size for no identity gain.
    unet.add_adapter(LoraConfig(
        r=args.rank, lora_alpha=args.rank,
        init_lora_weights="gaussian",
        target_modules=["to_k", "to_q", "to_v", "to_out.0"],
    ))
    cast_training_params(unet, dtype=torch.float32)
    params = [p for p in unet.parameters() if p.requires_grad]
    log.info("training %d LoRA tensors (rank %d, %.1fM params)",
             len(params), args.rank, sum(p.numel() for p in params) / 1e6)

    try:
        import bitsandbytes as bnb
        opt = bnb.optim.AdamW8bit(params, lr=args.lr)
        log.info("optimiser: AdamW8bit")
    except ImportError:
        opt = torch.optim.AdamW(params, lr=args.lr)
        log.info("optimiser: AdamW (install bitsandbytes for ~0.3 GB less VRAM)")

    noise_sched = DDPMScheduler.from_config(pipe.scheduler.config)
    scaler = torch.amp.GradScaler("cuda")
    add_time = torch.tensor([[size, size, 0, 0, size, size]], device=device, dtype=dtype)

    unet.train()
    order = itertools.cycle(range(len(records)))
    for step in range(1, args.steps + 1):
        rec = records[next(order)]
        latents = rec["latent"].unsqueeze(0).to(device, dtype=dtype)
        embeds = rec["prompt_embeds"].unsqueeze(0).to(device, dtype=dtype)

        noise = torch.randn_like(latents)
        t = torch.randint(0, noise_sched.config.num_train_timesteps, (1,), device=device).long()
        noisy = noise_sched.add_noise(latents, noise, t)

        kwargs = {}
        if is_sdxl:
            kwargs["added_cond_kwargs"] = {
                "text_embeds": rec["pooled"].unsqueeze(0).to(device, dtype=dtype),
                "time_ids": add_time,
            }

        with torch.autocast("cuda", dtype=torch.float16):
            pred = unet(noisy, t, encoder_hidden_states=embeds, **kwargs).sample
            target = (noise if noise_sched.config.prediction_type == "epsilon"
                      else noise_sched.get_velocity(latents, noise, t))
            loss = F.mse_loss(pred.float(), target.float(), reduction="mean")

        scaler.scale(loss / args.accum).backward()
        if step % args.accum == 0:
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(opt)
            scaler.update()
            opt.zero_grad(set_to_none=True)

        if step % 50 == 0 or step == 1:
            log.info("step %d/%d  loss %.4f  vram %.1f GB",
                     step, args.steps, loss.item(),
                     torch.cuda.max_memory_allocated() / 1024 ** 3)

    out_dir = char_dir / "lora"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"{char.name.lower()}_r{args.rank}_s{args.steps}"

    from diffusers.utils import convert_state_dict_to_diffusers
    from peft.utils import get_peft_model_state_dict
    sd = convert_state_dict_to_diffusers(get_peft_model_state_dict(unet))
    cls.save_lora_weights(str(out_dir), unet_lora_layers=sd,
                          weight_name=f"{name}.safetensors", safe_serialization=True)

    (out_dir / f"{name}.json").write_text(json.dumps({
        "character": char.name, "trigger": char.trigger, "base_kind": project.base_kind,
        "base_checkpoint": str(ckpt), "rank": args.rank, "steps": args.steps,
        "lr": args.lr, "resolution": size, "images": [str(p.name) for p in images],
    }, indent=2), encoding="utf-8")

    log.info("\nLoRA written: %s", out_dir / f"{name}.safetensors")
    log.info("Now set in %s:\n  lora_path: lora/%s.safetensors",
             char_dir / "character.yaml", name)
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="animstudio.train_lora",
        description="Train a character LoRA from characters/<name>/refs/",
    )
    p.add_argument("--character", required=True, help="path to characters/<name>/")
    p.add_argument("--project", help="path to config/project.yaml")
    p.add_argument("--steps", type=int, default=1200,
                   help="1000-1500 for 20 images; more overfits")
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--accum", type=int, default=4,
                   help="gradient accumulation; batch size is forced to 1 by VRAM")
    p.add_argument("--resolution", type=int, help="768 for SDXL, 512 for SD1.5")
    p.add_argument("--name", help="output file stem")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None):
    return train(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
