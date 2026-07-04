"""Bifrost MCP server for Ragnarok (Phase 0).

A standalone Model Context Protocol server that exposes Ragnarok's HTTP API as an
agent tool catalog. It is a thin, decoupled client of the *running* Ragnarok
backend (talks over HTTP to ``RAGNAROK_API_BASE``), so any MCP-capable agent —
Claude Code, Claude Desktop, Codex CLI, Gemini CLI, Goose, LibreChat, or a local
harness — can build, edit, solve, and analyse models with any model behind it.

Design + roadmap: ``docs/bifrost-agent.md``. This subpackage deliberately imports
**nothing** from ``backend.app`` at runtime (it only calls the REST API), which
keeps it portable to a standalone repo if we ever extract it.
"""
