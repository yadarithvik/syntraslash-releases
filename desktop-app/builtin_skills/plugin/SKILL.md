---
name: plugin
description: Create and import local Syntra plugin bundles containing reusable skills.
---

# Plugin

A Syntra local plugin is a folder with plugin.json and skill folders. Use a manifest such as {"name":"my-plugin","skills":["skills"]}, with skills/<name>/SKILL.md. Create files inside the selected workspace with write_file, include truthful descriptions and necessary resources, then inspect them. Import the folder using manage_extensions action plugin when installation is requested. Importing does not execute scripts, register hooks, copy credentials, or install MCP services. Enable imported guidance after reviewing the required dependencies. MCP services are separately configured through the MCP panel.
