# -*- coding: utf-8 -*-
"""Distill: source documents -> citable, chapter-split Markdown for AI retrieval.

Pipeline: pdf_extract (page rows/tables with coordinates) -> structure (TOC-driven
headings + chapter chunks) -> render (Markdown + indexes) -> verify (publish gate).
"""
