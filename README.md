# astrbot_plugin_group_auto_approve

# AstrBot QQ群自动审核插件

[English](#english) | [中文](#中文)

---

# 中文

## 简介

AstrBot QQ群自动审核插件是一个基于 AstrBot 开发的 QQ 群入群验证与审核管理插件。

本插件通过 OneBot V11 协议监听 QQ 群入群申请事件，获取申请者信息、验证问题与回答，并结合群名称、群公告调用大模型判断申请人答案是否正确，自动同意或拒绝入群申请。

---

## 功能特性

- ✅️ 监听 QQ 群入群申请事件
- ✅️ 获取申请者 QQ 信息（昵称、等级、头像）
- ✅️ 获取入群验证问题和回答
- ✅️ 获取群名称、最新群公告、最早群公告
- ✅️ 调用 AstrBot 当前配置的大模型判断答案是否正确
- ✅️ 自动同意入群申请
- ✅️ 自动拒绝入群申请，并由 AI 生成拒绝理由（30 字以内）
- ✅️ AI 调用失败时跳过处理，并在群内通知管理员
- ✅️ 支持开启/关闭入群申请监听
- ✅️ 支持 AstrBot 指令配置

---

## 安装方法

进入 AstrBot 插件目录：

```bash
cd AstrBot/data/plugins/
```
```
克隆本项目：
bash
git clone https://github.com/maruyui-dev/astrbot_plugin_group_auto_approve.git
```
重启 AstrBot 后插件会自动加载。

使用方法
查看帮助：

```
/验证 接收申请 帮助 或：/群组验证 接收申请 帮助
```
开启入群申请监听：

```
/验证 接收申请 切换 开
```
关闭入群申请监听：

```
/验证 接收申请 切换 关
```
查看当前开关状态（不带参数即可）：

```
/验证 接收申请 切换
```
工作流程  
监听 QQ 群入群申请事件 

获取申请者信息、群名称、群公告、验证问题与答案

调用 `AstrBot` 当前配置的大模型进行判断

模型返回 JSON：{"`correct`": `true`} 或 {"`correct`": `false`, "`reason`": "..."}

根据结果自动同意或拒绝入群申请

若 AI 调用失败，跳过处理并在群内通知管理员手动审核

开发进度
已完成

✅️ AstrBot 插件基础结构  
✅️ OneBot V11 request 事件监听  
✅️ 获取入群申请信息  
✅️ 获取验证问题和回答  
✅️ 获取群名称与群公告  
✅️ 接收申请开关控制  
✅️ AI 自动验证答案  
✅️ 自动同意入群申请  
✅️ 自动拒绝入群申请并生成拒绝理由

计划功能

🟩 黑名单系统  
🟩 白名单系统  
🟩 多群独立配置  
🟩 等级限制审核  
🟩 WebUI 配置支持

技术栈
* Python

* AstrBot Plugin API

* OneBot V11 Protocol

环境要求
* Python 3.10+

* AstrBot

* OneBot V11 实现端（例如 NapCat）

注意事项
使用本插件前请确保：

* AstrBot 已正常运行

* OneBot V11 已连接

* QQ机器人拥有群管理相关权限

* AstrBot 已配置可用的聊天模型（用于 AI 验证）

* 群公告接口 _get_group_notice 在当前协议端可用

# English 
## Introduction
AstrBot QQ Group Auto Verification Plugin is a plugin developed for AstrBot.

It monitors QQ group join requests through the OneBot V11 protocol, extracts applicant information, group name, group notices, and verification answers, then uses the LLM configured in AstrBot to judge whether the applicant's answer is correct, automatically approving or rejecting the request.

Features  
✅️ Monitor QQ group join requests  
✅️ Retrieve applicant information (nickname, level, avatar)  
✅️ Extract verification questions and answers  
✅️ Retrieve group name, latest notice, earliest notice  
✅️ Use the LLM configured in AstrBot to verify answers  
✅️ Automatically approve join requests  
✅️ Automatically reject join requests with an AI-generated reason (within 30 characters)  
✅️ Skip processing and notify admins when the LLM call fails  
✅️ Enable or disable request monitoring  
✅️ Configure plugin behavior through AstrBot commands

Installation  
Clone this repository into:
```
AstrBot/data/plugins/
```
Example:
```
bash
git clone https://github.com/maruyui-dev/astrbot_plugin_group_auto_approve.git
```
Restart AstrBot after installation.

Usage
View help:
```
/验证 接收申请 帮助
```
Enable request monitoring:
```
/验证 接收申请 切换 开
```
Disable request monitoring:  
```
/验证 接收申请 切换 关
```
Check current status:

```
/验证 接收申请 切换
```
Workflow  
Listen for QQ group join requests  
Collect applicant info, group name, group notices, question and answer  
Call the `LLM` configured in AstrBot  
Model returns JSON: {"`correct`": `true`} or {"`correct`": `false`, "`reason`": "..."}

Automatically approve or reject based on the result  
If the LLM call fails, skip processing and notify admins  
Development Roadmap
Completed

✅️ AstrBot plugin framework  
✅️ OneBot V11 request event listener  
✅️ Applicant information extraction  
✅️ Verification question extraction  
✅️ Group name and notice retrieval  
✅️ Request monitoring switch  
✅️ AI-based answer verification  
✅️ Automatic approval  
✅️ Automatic rejection with AI-generated reason

Planned

🟩 Blacklist management  
🟩 Whitelist management  
🟩 Multi-group configuration  
🟩 Level-based verification  
🟩 WebUI configuration

Requirements
* Python 3.10+

* AstrBot

* OneBot V11 compatible implementation

License
* MIT License

# Supports

- [AstrBot Repo](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot Plugin Development Docs (Chinese)](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot Plugin Development Docs (English)](https://docs.astrbot.app/en/dev/star/plugin-new.html)