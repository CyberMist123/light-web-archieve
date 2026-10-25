# 功能 → 测试对照（ARCH-AUDIT 第 0 批，1023）

两部分：①模块有没有测试碰到（按测试文件里出现模块名粗算，机器生成，只说明「有人测」不说明「测全」）；②**行为缺口**——排查出的问题对应的用例现在都没有，按批次补。

## ① 行为缺口（要补的用例）

| 行为 | 现在 | 补在哪批 |
|---|---|---|
| 同步中断后，新帖出现在目录 | ✅ `test_catalog_fresh_1023.py::test_sync_run_refreshes_catalog_even_when_it_fails`（1023） | 1 |
| 单篇导入（catch / MCP / CLI）、从快照恢复、改来源、专辑同步后目录更新 | 无（1025 核：`test_catalog_fresh_1023.py::test_catch_refreshes_unless_deferred` 只覆盖 catch 单篇这一段，其余没覆盖）；1025 晚补：从快照恢复、改来源两段由 `test_refresh_after_restore_relabel.py` 覆盖（mark_dirty 理由 + ensure_fresh；dry_run 不动目录），专辑同步仍无 | 1 |
| 内容没变时重建不改任何页面文件（不刷屏） | ✅ `test_catalog_fresh_1023.py::test_rebuild_without_changes_touches_no_file`（1023） | 1 |
| 目录页和问收藏页的「全部」篇数相等 | ✅ `test_catalog_fresh_1023.py::test_counts_single_source`（1023） | 1 |
| 同一条用量，账本 / 预算 / 夜跑花费 / 设置页显示的钱一致；未知模型 = 未计价 | ✅ `test_pricing_1023.py`（1023） | 2 |
| 概要切 CLI（OpenCode）能跑、记账显示免费 | ✅ `test_pricing_1023.py` + `test_ai_settings_ui.cjs`（1023） | 2 |
| 夜跑和 providers 拿到同一组 Gemini key | ✅ `test_pricing_1023.py`（1023） | 2 |
| TG 发来的帖来源 = Fable；多号收藏、网页导入 = 我的收藏 | ✅ `test_domain.py`（1025 第二波 PR①：规则进 domain.py；`test_provenance_1020.py` 改成新口径） | 3（规则部分已做；user_id / 专辑键迁移待做） |
| 换号同步不清掉另一个号的专辑；重抓不丢收藏标记 | 无 | 3 |
| 关掉视频下载时不下视频、原帖链接保留 | ✅ `test_video_download_off.py`（1025，本机 main 上绿：现状本来就不下） | 2 |
| 旅行等内置 skill 的回答质量 | 只在问答用例里顺带出现，未验收 | 并行（找 skill） |
| 页面标题 / 文案只从一处来 | 守卫 `test_guards.py` | 4 |

## ② 模块 → 测试文件（碰到该模块的测试数 · 前几个）

| 模块 | 测试数 | 例子 |
|---|---|---|
| `link_brain/__main__.py` | 0 |  |
| `link_brain/sources/xiaohongshu/accounts.py` | 28 | test_account_guard_1008.py, test_account_safety.py, test_accounts.py, test_albums_1019.py … |
| `link_brain/actionlog.py` | 2 | test_panel_1017.py, test_risk1016.py |
| `link_brain/sources/xiaohongshu/adapter.py` | 106 | catalog_plus_ui.cjs, chat_board_ui.cjs, chat_ui_rig.cjs, note_first_frame_ui.cjs … |
| `link_brain/agentmd.py` | 3 | test_agentmd_1008.py, test_chatter_report_1015.py, test_vision_doubt_1017.py |
| `link_brain/ai_config.py` | 36 | test_ai_health_1008.py, test_answer_cache.py, test_ask.py, test_ask_b2_1015.py … |
| `link_brain/ai_health.py` | 7 | test_ai_health_1008.py, test_card_problems_1008.py, test_console_1018.py, test_fix_1016.py … |
| `link_brain/ai_routes.py` | 1 | test_console_1018.py |
| `link_brain/sources/xiaohongshu/albums.py` | 3 | test_albums_1019.py, test_catalog_interactions.cjs, test_mcp_browse_1018.py |
| `link_brain/alert.py` | 27 | test_account_safety.py, test_accounts.py, test_alert.py, test_attachments_recheck_1008.py … |
| `link_brain/answer_cache.py` | 6 | test_answer_cache.py, test_ask_b3_r3.py, test_ask_r2_session.py, test_ask_ui2_1004.py … |
| `link_brain/answer_check.py` | 3 | test_ask_stage1_1017.py, test_ask_v21_1018.py, test_cite_jump_1021.py |
| `link_brain/answer_prompt.py` | 4 | test_ask.py, test_ask_ui2_1004.py, test_ask_v21_1018.py, test_cite_jump_1021.py |
| `link_brain/ask.py` | 63 | catalog_ui_smoke.cjs, chat_b2_ui.cjs, chat_board_ui.cjs, chat_ui_rig.cjs … |
| `link_brain/ask_followup.py` | 2 | test_ask_v21_1018.py, test_cite_jump_1021.py |
| `link_brain/ask_intent.py` | 5 | test_albums_1019.py, test_ask_b2_1015.py, test_ask_b3_r1.py, test_ask_stage1_1017.py … |
| `link_brain/ask_turns.py` | 3 | test_ask_b2_1015.py, test_ask_b3_r1.py, test_ask_v21_1018.py |
| `link_brain/asr.py` | 10 | l4_settings_ui.cjs, test_ai_settings_ui.cjs, test_asr.py, test_home_ui.cjs … |
| `link_brain/assets/annotate-view.js` | 10 | test_annot_1008.cjs, test_annot_reply_1020.cjs, test_annot_side.cjs, test_annotate_merge.cjs … |
| `link_brain/assets/catalog-search.js` | 24 | test_ask_sources_b10.cjs, test_batch3_ui.cjs, test_batch4_ui.cjs, test_batch6_report_ui.cjs … |
| `link_brain/assets/catalog-view.js` | 14 | test_batch3_ui.cjs, test_batch4_ui.cjs, test_batch6_report_ui.cjs, test_batch9_synclog_ui.cjs … |
| `link_brain/assets/chat-view.js` | 15 | test_ask_sources_b10.cjs, test_batch3_ui.cjs, test_catalog_slim.cjs, test_chat_b2_1015.cjs … |
| `link_brain/assets/lb-page-lib.js` | 28 | page_lib_ui.cjs, rig_selfcheck_ui.cjs, test_annot_1008.cjs, test_annot_reply_1020.cjs … |
| `link_brain/assets/page-bootstrap.js` | 3 | catalog_fast_open_ui.cjs, test_page_code_version_1020.cjs, test_page_lib_1002.py |
| `link_brain/assets/trash-view.js` | 1 | test_trash_view_c16.cjs |
| `link_brain/attachments.py` | 41 | test_account_safety.py, test_accounts.py, test_accounts_ui.cjs, test_ask_v21_1018.py … |
| `link_brain/budget.py` | 13 | catalog_ui_smoke.cjs, l4_settings_ui.cjs, test_ask_r2.py, test_attachments_recheck_1008.py … |
| `link_brain/catalog.py` | 107 | catalog_after_note_ui.cjs, catalog_arrange_ui.cjs, catalog_fast_open_ui.cjs, catalog_first_render_ui.cjs … |
| `link_brain/catch.py` | 114 | catalog_after_note_ui.cjs, catalog_arrange_ui.cjs, catalog_fast_open_ui.cjs, catalog_first_render_ui.cjs … |
| `link_brain/cli.py` | 77 | test_account_safety.py, test_ai_health_1008.py, test_alert.py, test_annotations_1001.py … |
| `link_brain/sources/xiaohongshu/comment_fill.py` | 10 | test_comments_fill_1008.py, test_comments_fill_1009.py, test_comments_resume_1017.py, test_fix_1016.py … |
| `link_brain/comments.py` | 63 | chat_b2_ui.cjs, chat_ui_rig.cjs, evidence_ui.cjs, index_inplace_ui.cjs … |
| `link_brain/connect.py` | 24 | l4_settings_ui.cjs, test_atomic_writes_1001.py, test_attachments.py, test_attachments_integrity_1001.py … |
| `link_brain/crawl.py` | 1 | test_risk1016.py |
| `link_brain/docconv.py` | 1 | test_pdftext.py |
| `link_brain/doctor.py` | 6 | test_accounts.py, test_accounts_ui.cjs, test_batch5_delivery.py, test_batch5_delivery_ui.cjs … |
| `link_brain/enrich.py` | 20 | test_ai_health_1008.py, test_batch4_ui.cjs, test_batch5_delivery.py, test_card_problems_1008.py … |
| `link_brain/errtext.py` | 1 | test_errtext.py |
| `link_brain/evidence_pack.py` | 1 | test_ask_b3_r1.py |
| `link_brain/export_bundle.py` | 3 | test_answer_cache.py, test_export_bundle.py, test_mdsafe.py |
| `link_brain/sources/xiaohongshu/fav_counts.py` | 3 | test_setup.py, test_guards.py, test_sync_truth_1011.py |
| `link_brain/sources/xiaohongshu/favorites.py` | 39 | test_account_safety.py, test_accounts.py, test_accounts_ui.cjs, test_attachments_recheck_1008.py … |
| `link_brain/history.py` | 25 | test_answer_cache.py, test_ask_b2_1015.py, test_ask_eval.py, test_ask_v21_1018.py … |
| `link_brain/index.py` | 71 | catalog_search_index_ui.cjs, index_inplace_ui.cjs, index_outline_ui.cjs, index_tree_ui.cjs … |
| `link_brain/indexai.py` | 2 | test_indexai_1011.py, test_indexedit_1015.py |
| `link_brain/indexedit.py` | 1 | test_indexedit_1015.py |
| `link_brain/indextree.py` | 5 | test_catalog_slim_1001.py, test_indexai_1011.py, test_indexedit_1015.py, test_indextree_1010.py … |
| `link_brain/ingest.py` | 31 | test_alert.py, test_annotate_merge.cjs, test_annotations_1001.py, test_atomic_writes_1001.py … |
| `link_brain/keyprobe.py` | 2 | test_keyprobe_1018.py, test_guards.py |
| `link_brain/llm.py` | 16 | test_ai_health_1008.py, test_catalog_search.cjs, test_cite_jump_1021.py, test_comments_fill_1008.py … |
| `link_brain/mcp_server.py` | 2 | test_mcp_server.py, test_mcp_tools.py |
| `link_brain/mcp_tools.py` | 6 | test_ask_b2_1015.py, test_ask_v21_1018.py, test_mcp_browse_1018.py, test_mcp_tools.py … |
| `link_brain/mdsafe.py` | 2 | test_mdsafe.cjs, test_mdsafe.py |
| `link_brain/mention.py` | 2 | test_annot_reply_1020.cjs, test_mention_1020.py |
| `link_brain/sources/xiaohongshu/night_captcha.py` | 2 | test_night_captcha_1011.py, test_ratelimit_1015.py |
| `link_brain/nightly.py` | 18 | test_attachments_recheck_1008.py, test_batch5_delivery.py, test_batch9_synclog_ui.cjs, test_catalog_mobile_c12.cjs … |
| `link_brain/note.py` | 126 | catalog_after_note_ui.cjs, catalog_plus_side_ui.cjs, catalog_ui_smoke.cjs, chat_b2_ui.cjs … |
| `link_brain/note_print.py` | 2 | test_export_bundle.py, test_note_print_1009.py |
| `link_brain/ocrtext.py` | 1 | test_ocrtext.py |
| `link_brain/pdftext.py` | 5 | test_attachments_integrity_1001.py, test_mdsafe.py, test_pdftext.py, test_problems_batch4.py … |
| `link_brain/pickfolder.py` | 1 | test_pickfolder_1009.py |
| `link_brain/places.py` | 2 | test_ask_b3_r3.py, test_recall_b10.py |
| `link_brain/playlist.py` | 4 | media_controls_ui.cjs, test_media_nav_1008.cjs, test_player_ui_1009.cjs, test_playlist_1009.py |
| `link_brain/posttags.py` | 2 | test_indexai_1011.py, test_indexedit_1015.py |
| `link_brain/pricing.py` | 1 | test_pricing_1023.py（1023 新建：价格 / 免费 / 提供商唯一来源） |
| `link_brain/problems.py` | 48 | l4_settings_ui.cjs, test_accounts.py, test_ai_health_1008.py, test_ask_b2_1015.py, test_problems_merged_marker_1025.py … |
| `link_brain/procs.py` | 4 | test_batch5_delivery.py, test_cli_call_timeout.py, test_note_print_1009.py, test_procs.py |
| `link_brain/provenance.py` | 2 | test_provenance_1020.py, test_guards.py |
| `link_brain/providers.py` | 18 | l4_settings_ui.cjs, test_ai_health_1008.py, test_asr.py, test_console_1018.py … |
| `link_brain/read.py` | 50 | catalog_search_index_ui.cjs, catalog_ui_smoke.cjs, chat_board_ui.cjs, chat_ui_rig.cjs … |
| `link_brain/sources/xiaohongshu/reader_install.py` | 1 | test_batch5_delivery.py |
| `link_brain/recall_core.py` | 2 | test_ask_b2_1015.py, test_recall_r1.py |
| `link_brain/recall_table.py` | 2 | test_ask_stage1_1017.py, test_recall_table_1017.py |
| `link_brain/remote/cli.py` | 77 | test_account_safety.py, test_ai_health_1008.py, test_alert.py, test_annotations_1001.py … |
| `link_brain/remote/config.py` | 15 | chat_ui_rig.cjs, test_accounts.py, test_batch5_delivery.py, test_batch5_delivery_ui.cjs … |
| `link_brain/remote/policy.py` | 10 | test_ask_b2_1015.py, test_ask_v21_1018.py, test_mcp_browse_1018.py, test_mcp_tools.py … |
| `link_brain/remote/secret_box.py` | 1 | test_remote_1009.py |
| `link_brain/remote/server.py` | 7 | test_batch5_delivery.py, test_mcp_server.py, test_recall_table_1017.py, test_remote_cli.py … |
| `link_brain/remote/store.py` | 4 | test_remote_1009.py, test_remote_cli.py, test_remote_images.py, test_remote_mcp.py |
| `link_brain/remote/task.py` | 12 | catalog_arrange_ui.cjs, catalog_plus_side_ui.cjs, l4_settings_ui.cjs, test_ask_v21_1018.py … |
| `link_brain/remote/tools.py` | 20 | catalog_arrange_ui.cjs, media_controls_ui.cjs, note_header_ui.cjs, note_page_ui.cjs … |
| `link_brain/remove.py` | 38 | catalog_after_note_ui.cjs, catalog_fast_open_ui.cjs, catalog_ui_smoke.cjs, l4_settings_ui.cjs … |
| `link_brain/render.py` | 48 | catalog_first_render_ui.cjs, chat_b2_ui.cjs, chat_board_ui.cjs, chat_ui_rig.cjs … |
| `link_brain/repair.py` | 16 | test_ai_health_1008.py, test_attachments_recheck_1008.py, test_batch4_ui.cjs, test_comments_fill_1009.py … |
| `link_brain/report.py` | 41 | chat_board_ui.cjs, note_first_frame_ui.cjs, test_accounts.py, test_ai_health_1008.py … |
| `link_brain/rerank.py` | 5 | l4_settings_ui.cjs, test_ask_b3_r1.py, test_catalog_order_c2.cjs, test_rerank_r2.py … |
| `link_brain/restore.py` | 14 | catalog_fast_open_ui.cjs, test_catalog_pending_n9.cjs, test_chat_smooth_l2.cjs, test_chat_ui2_1004.cjs … |
| `link_brain/sources/xiaohongshu/restricted.py` | 7 | test_fix_1016.py, test_note_restricted_1011.cjs, test_panel_1017.py, test_problems_dismiss_ui.cjs … |
| `link_brain/retrieval.py` | 24 | test_ask_b2_1015.py, test_ask_b3_r3.py, test_ask_board_1020.py, test_ask_eval.py … |
| `link_brain/saved_sources.py` | 1 | test_ask_ui2_1004.py |
| `link_brain/screentext.py` | 3 | test_agentmd_1008.py, test_videos_transcribe_1001.py, test_visual_voice.py |
| `link_brain/selections.py` | 5 | test_catalog_ui_1004.cjs, test_mcp_server.py, test_mcp_tools.py, test_remote_mcp.py … |
| `link_brain/semantic.py` | 13 | test_answer_cache.py, test_ask_b2_1015.py, test_ask_evidence_1001.py, test_ask_r0.py … |
| `link_brain/serve.py` | 5 | test_batch3_feedback.py, test_batch5_delivery_ui.cjs, test_remote_cli.py, test_serve_stdin.py … |
| `link_brain/setup/backfill.py` | 3 | test_setup.py, test_sync_truth_1011.py, test_synclog.py |
| `link_brain/setup/capswriter.py` | 8 | test_asr.py, test_catalog_interactions.cjs, test_home_ui.cjs, test_providers.py … |
| `link_brain/setup/common.py` | 1 | test_setup.py |
| `link_brain/setup/components.py` | 5 | l4_settings_ui.cjs, test_home_ui.cjs, test_settings_layout.cjs, test_setup.py … |
| `link_brain/setup/estimate.py` | 9 | l4_settings_ui.cjs, test_index_ui_1010.cjs, test_indexai_1011.py, test_indexedit_1015.py … |
| `link_brain/setup/fetch.py` | 10 | note_header_ui.cjs, test_comment_fetch_1010.cjs, test_note_actions_1008.cjs, test_note_render_1008.py … |
| `link_brain/setup/pipeline.py` | 1 | test_setup_run_1009.py |
| `link_brain/setup/sysinfo.py` | 1 | test_setup.py |
| `link_brain/skills.py` | 9 | l4_settings_ui.cjs, test_ask_b2_1015.py, test_ask_board_1020.py, test_batch5_delivery_ui.cjs … |
| `link_brain/storage.py` | 92 | test_ai_health_1008.py, test_alert.py, test_annotations_1001.py, test_answer_cache.py … |
| `link_brain/sync_schedule.py` | 2 | test_batch5_delivery.py, test_sync_schedule.py |
| `link_brain/sync_state.py` | 19 | test_account_safety.py, test_accounts.py, test_batch5_delivery.py, test_fav_incremental_1011.py … |
| `link_brain/synclog.py` | 9 | test_batch9_synclog_ui.cjs, test_catalog_mobile_c12.cjs, test_comments_fill_1008.py, test_guards.py … |
| `link_brain/text_stream.py` | 12 | test_ask_b2_1015.py, test_batch3_feedback.py, test_cli_call_timeout.py, test_hardening_1001.py … |
| `link_brain/topics.py` | 20 | catalog_plus_ui.cjs, catalog_ui_smoke.cjs, test_batch3_ui.cjs, test_batch4_ui.cjs … |
| `link_brain/usage.py` | 17 | l4_settings_ui.cjs, test_ask_b2_1015.py, test_batch5_delivery_ui.cjs, test_catalog.py … |
| `link_brain/videos.py` | 12 | test_batch5_delivery.py, test_night_captcha_1011.py, test_problems.py, test_problems_batch4.py … |
| `link_brain/vision.py` | 49 | l4_settings_ui.cjs, test_agentmd_1008.py, test_ai_health_1008.py, test_ai_settings_ui.cjs … |
| `link_brain/visual.py` | 20 | test_agentmd_1008.py, test_ask_v21_1018.py, test_attachments_integrity_1001.py, test_card_problems_1008.py … |
| `link_brain/voice.py` | 6 | l4_settings_ui.cjs, test_asr.py, test_home_ui.cjs, test_settings_layout.cjs … |
| `link_brain/watch.py` | 3 | catalog_ui_smoke.cjs, test_batch4_ui.cjs, test_risk1016.py |
| `link_brain/wiki.py` | 16 | chat_board_ui.cjs, index_inplace_ui.cjs, index_outline_ui.cjs, index_tree_ui.cjs … |
| `obsidian-plugins/link-brain-actions/home-ui.js` | 3 | test_batch5_delivery.py, test_home_ui.cjs, test_settings_layout.cjs |
| `obsidian-plugins/link-brain-actions/image-actions.js` | 3 | test_image_actions_1009.cjs, test_plugin_foundation.cjs, test_synth_vault_tool.py |
| `obsidian-plugins/link-brain-actions/index-ui.js` | 5 | l4_settings_ui.cjs, test_index_ui_1010.cjs, test_plugin_foundation.cjs, test_settings_layout.cjs … |
| `obsidian-plugins/link-brain-actions/library-ui.js` | 1 | catalog_ui_smoke.cjs |
| `obsidian-plugins/link-brain-actions/main.js` | 35 | evidence_ui.cjs, l4_settings_ui.cjs, note_first_frame_ui.cjs, test_accounts_ui.cjs … |
| `obsidian-plugins/link-brain-actions/media-nav.js` | 8 | catalog_after_note_ui.cjs, media_controls_ui.cjs, note_page_ui.cjs, test_batch5_delivery.py … |
| `obsidian-plugins/link-brain-actions/note-actions.js` | 8 | note_header_ui.cjs, note_highlight_ui.cjs, test_comment_fetch_1010.cjs, test_comments_progress_1010.py … |
| `obsidian-plugins/link-brain-actions/note-tools.js` | 4 | note_header_ui.cjs, test_note_tools_1009.cjs, test_plugin_foundation.cjs, test_synth_vault_tool.py |
| `obsidian-plugins/link-brain-actions/onboarding-ui.js` | 4 | l4_settings_ui.cjs, test_batch5_delivery.py, test_batch5_delivery_ui.cjs, test_settings_layout.cjs |
| `obsidian-plugins/link-brain-actions/player-ui.js` | 3 | test_player_ui_1009.cjs, test_plugin_foundation.cjs, test_synth_vault_tool.py |
| `obsidian-plugins/link-brain-actions/problems-ui.js` | 5 | test_batch4_ui.cjs, test_note_restricted_1011.cjs, test_problems_dismiss_ui.cjs, test_guards.py … |
| `obsidian-plugins/link-brain-actions/provider-icons.js` | 1 | test_settings_layout.cjs |
| `obsidian-plugins/link-brain-actions/remote-ui.js` | 4 | l4_settings_ui.cjs, test_remote_cli.py, test_remote_ui.cjs, test_settings_layout.cjs |
| `obsidian-plugins/link-brain-actions/report-ui.js` | 2 | test_batch9_synclog_ui.cjs, test_synclog_truth_1011.cjs |
| `obsidian-plugins/link-brain-actions/schedule-ui.js` | 2 | test_batch9_synclog_ui.cjs, test_settings_layout.cjs |
| `obsidian-plugins/link-brain-actions/settings-pages.js` | 4 | test_ai_settings_ui.cjs, test_settings_layout.cjs, test_settings_pages_1016.cjs, test_guards.py |
| `obsidian-plugins/link-brain-actions/settings-v6.js` | 2 | test_settings_layout.cjs, test_guards.py |
| `obsidian-plugins/link-brain-actions/skills-ui.js` | 2 | test_settings_layout.cjs, test_skills_ui_1015.cjs |
| `obsidian-plugins/link-brain-actions/usage-ui.js` | 3 | l4_settings_ui.cjs, test_settings_layout.cjs, test_usage_ui.cjs |

重新生成：见 ARCH-AUDIT 第 0 批（按模块名在 `tests/` 里搜）。数字只是线索：1 个测试碰到不代表测全，0 个不一定没测（可能经别的模块间接测）。
