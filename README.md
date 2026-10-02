# astrbot_plugin_group_auto_approve

# AstrBot QQ群自动审核插件

[English](#english) | [中文](#中文)

---

# 中文

## 简介

AstrBot QQ群自动审核插件是一个基于 AstrBot 开发的 QQ 群入群验证与审核管理插件。

本插件通过 OneBot V11 协议监听 QQ 群入群申请事件，可以获取申请者信息、验证问题以及回答内容，并提供基础的审核配置管理功能。

项目目前处于开发阶段，未来将支持更加完善的自动审核逻辑。

---

## 功能特性

- ✅ 监听 QQ 群入群申请事件
- ✅ 获取申请者 QQ 信息
- ✅ 获取入群验证问题和回答
- ✅ 支持开启/关闭入群申请监听
- ✅ 支持 AstrBot 指令配置
- 🚧 自动审核功能开发中

---

## 安装方法

进入 AstrBot 插件目录：

```bash
cd AstrBot/data/plugins/
```
```
克隆本项目：
git clone https://github.com/maruyui-dev/astrbot_plugin_group_auto_approve.git
```
重启 AstrBot 后插件会自动加载。  
使用方法  
查看帮助  
发送：
/验证
或者：
/群组验证

开启入群申请监听:  
/验证 接收申请 开

关闭入群申请监听:  
/验证 接收申请 关

开发进度
已完成
- [x] AstrBot 插件基础结构
- [x] OneBot V11 request 事件监听
- [x] 获取入群申请信息
- [x] 获取验证问题和回答
- [x] 接收申请开关控制
计划功能
- [ ] 自动验证答案
- [ ] 自动同意入群申请
- [ ] 自动拒绝入群申请
- [ ] 黑名单系统
- [ ] 白名单系统
- [ ] 多群独立配置
- [ ] WebUI 配置支持
技术栈
- Python
- AstrBot Plugin API
- OneBot V11 Protocol
环境要求
- Python 3.10+
- AstrBot
- OneBot V11 实现端（例如 NapCat）
注意事项
使用本插件前请确保：
>1. AstrBot 已正常运行
>2. OneBot V11 已连接
>3. QQ机器人拥有群管理相关权限
>
English
Introduction  
AstrBot QQ Group Auto Verification Plugin is a plugin developed for AstrBot.
It monitors QQ group join requests through the OneBot V11 protocol, extracts applicant information and verification answers, and provides basic configuration management.
This project is currently under active development.
Features
- Monitor QQ group join requests
- Receive applicant information
- Extract verification questions and answers
- Enable or disable join request monitoring
- Configure plugin behavior through AstrBot commands
Installation
Clone this repository into:
AstrBot/data/plugins/

Example:
git clone https://github.com/maruyui-dev/astrbot_plugin_group_auto_approve.git

Restart AstrBot after installation.
Development Roadmap
Completed
- [x] AstrBot plugin framework
- [x] OneBot V11 request event listener
- [x] Applicant information extraction
- [x] Verification question extraction
- [x] Request monitoring switch
Planned
- [ ] Automatic approval system
- [ ] Automatic rejection system
- [ ] Blacklist management
- [ ] Whitelist management
- [ ] Multi-group configuration
- [ ] WebUI configuration
Requirements
- Python 3.10+
- AstrBot
- OneBot V11 compatible implementation
License
MIT License

# Supports

- [AstrBot Repo](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot Plugin Development Docs (Chinese)](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot Plugin Development Docs (English)](https://docs.astrbot.app/en/dev/star/plugin-new.html)
