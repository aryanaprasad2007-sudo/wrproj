"""Command line entry point.

    py -m animstudio render shots.yaml --preset draft
    py -m animstudio render shots.yaml --only s04,s05 --stage video,post
    py -m animstudio render shots.yaml --dry-run
    py -m animstudio assemble shots.yaml
    py -m animstudio doctor

`--stage` exists because the four stages have wildly different costs, and the
one you iterate on is almost always Stage A. Rendering keyframes alone for a
40-shot film takes minutes; the full run takes hours. Judge composition and
character consistency on the stills first.
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from . import config, hardware, pipeline, progress

log = logging.getLogger(__name__)


def _default_project(root: pathlib.Path) -> pathlib.Path:
    for c in (root / "config" / "project.yaml", root / "config" / "project.example.yaml"):
        if c.exists():
            return c
    return root / "config" / "project.yaml"


def _load(args):
    root = pathlib.Path(__file__).resolve().parents[2]
    cfg = config.ProjectConfig.load(args.project or _default_project(root))
    shotlist = config.ShotList.load(args.shots)
    preset = cfg.preset(args.preset)
    film = args.film or shotlist.title
    return cfg, shotlist, preset, film


def cmd_render(args):
    cfg, shotlist, preset, film = _load(args)
    progress.setup_logging(args.verbose, cfg.work_root / film / "render.log")
    pipe = pipeline.Pipeline(cfg, film)
    stages = tuple(s.strip() for s in args.stage.split(",")) if args.stage else pipeline.Pipeline.STAGES
    bad = set(stages) - set(pipeline.Pipeline.STAGES)
    if bad:
        raise SystemExit(f"unknown stage(s) {sorted(bad)}; "
                         f"choose from {', '.join(pipeline.Pipeline.STAGES)}")
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    pipe.run(shotlist, preset, only=only, stages=stages,
             resume=args.resume, dry_run=args.dry_run)
    return 0


def cmd_assemble(args):
    cfg, shotlist, preset, film = _load(args)
    progress.setup_logging(args.verbose)
    pipe = pipeline.Pipeline(cfg, film)
    out = pipe.assemble_film(shotlist.select(None), shotlist, preset)
    print(f"\nfilm: {out}")
    return 0


def cmd_doctor(args):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
    import doctor
    return doctor.main([])


def build_parser():
    p = argparse.ArgumentParser(prog="animstudio",
                                description="Local shot-based AI animation pipeline")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("shots", help="path to the shot list YAML")
        sp.add_argument("--project", help="path to project.yaml")
        sp.add_argument("--preset", help="draft | high | any preset you define")
        sp.add_argument("--film", help="output name (defaults to the shot list title)")

    r = sub.add_parser("render", help="render shots and assemble the film")
    common(r)
    r.add_argument("--only", help="comma-separated shot ids to (re)render")
    r.add_argument("--stage", help="comma-separated: keyframe,video,post,assemble")
    r.add_argument("--resume", action="store_true",
                   help="skip shots already marked ok in run.jsonl")
    r.add_argument("--dry-run", action="store_true",
                   help="validate the shot list and estimate time; loads no models")
    r.set_defaults(func=cmd_render)

    a = sub.add_parser("assemble", help="re-assemble from existing clips (no GPU)")
    common(a)
    a.set_defaults(func=cmd_assemble)

    d = sub.add_parser("doctor", help="check the install and report the hardware")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as exc:
        progress.setup_logging(False)
        log.error("config error: %s", exc)
        return 2
    except KeyboardInterrupt:
        log.warning("interrupted -- rerun with --resume to continue")
        return 130


if __name__ == "__main__":
    sys.exit(main())
