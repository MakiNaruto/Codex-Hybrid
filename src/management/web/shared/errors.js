'use strict';
function managementErrorMessage(error,sourceMode){
  const common={
    CODEX_NOT_READY:'请先安装并登录 Codex，确认本地官方配置与模型缓存可读取，再重试初始化。',
    NOT_CONFIGURED:'请先初始化管理配置。',
    INVALID_PREVIEW:'预览已失效，请重新预览并确认。',
    OPERATION_FAILED:'操作未完成，请刷新状态并检查配置后重试。',
    MODEL_SOURCE_CHANGED:'配置来源已变化，请关闭弹窗，刷新后重新选择模型。',
    MODEL_DISABLED_AT_SOURCE:'此模型在来源中已停用，请先在管理连接或 CC Switch 中启用。',
    INVALID_MODEL_PREFERENCES:'模型设置格式无效，请刷新后重试。',
    INSTANCE_BUSY:'其他进程正在操作此数据目录，请等待完成后刷新重试。',
    SERVICE_ALREADY_RUNNING:'此数据目录已有服务运行，未重复启动。',
    FORWARDING_START_FAILED:'模型转发未能启动，请查看转发状态中的故障原因；管理页面仍可使用。',
    FORWARDING_UNAVAILABLE:'当前无法恢复模型转发，请检查接入配置。',
    OPERATION_TIMEOUT:'操作等待超时，结果尚未确认。请刷新状态后检查，不要连续重复提交。',
    SERVICE_UNREACHABLE:'无法连接本地服务，请确认服务已启动后重试。',
    INVALID_SERVICE_RESPONSE:'服务返回了无法读取的响应，请刷新页面或检查服务日志。',
    CREDENTIALS_NOT_FOUND:'未找到 API Key，请填写并保存，或检查凭据环境变量。',
    CONFIG_INVALID_IDENTIFIER:'厂商标识和模型别名仅支持字母、数字、点、下划线和连字符，且须以字母或数字开头。',
    CONFIG_INVALID_BASE_URL:'API 地址需要有效的 HTTPS 基础地址，不要包含具体接口路径（如 /responses）。',
    CONFIG_INVALID_LIMIT:'上下文、输出上限或超时时间须为支持范围内的正整数。',
    CONFIG_RESERVED_PARAMETER:'高级参数包含模型、消息、认证或输出预算等保留字段，请使用对应表单设置。',
    CONFIG_INVALID_PARAMETERS:'高级参数必须是 JSON 对象。',
    CONFIG_UNSUPPORTED_PROTOCOL:'仅支持 Responses API，请将厂商配置改为 openai_responses 并确认供应商支持 /responses。',
    CONFIG_MISSING_FIELD:'配置缺少必要字段，请检查厂商与模型信息。',
    UPSTREAM_STREAM_ENDED_EARLY:'上游连接已结束，但没有收到完成信号。请检查协议及模型是否匹配。',
    UPSTREAM_OUTPUT_BUDGET_EXHAUSTED:'连接测试达到输出预算，尚未完整完成，请检查模型输出设置。',
    UPSTREAM_INCOMPLETE:'上游返回未完成响应，请检查服务状态。'
  };
  if(common[error.message])return common[error.message];
  if(error instanceof SyntaxError)return '高级参数 JSON 格式有误，请检查逗号、引号和括号。';
  const routingErrors={
    SESSION_BACKUP_TIMEOUT:'会话索引备份等待超时，接入配置尚未切换。请关闭占用数据库的程序后重新预览并重试。',
    SESSION_MIGRATION_PROCESS_CHECK_FAILED:'无法读取 Codex 进程状态。开启或关闭接入时可重新预览并确认影响后继续；恢复备份前请检查系统权限。',
    SESSION_MIGRATION_CODEX_RUNNING:'检测到相关 Codex 进程。开启或关闭接入时可重新预览并确认影响后继续；CLI 迁移前请先退出 Codex。',
    SESSION_MIGRATION_CHANGED:'会话在预览后发生变化，请重新预览并重试。',
    SESSION_INDEX_CODEX_UNAVAILABLE:'未找到可用的 Codex 程序，无法补齐会话索引。请安装 Codex，或在实例设置中指定 codex_executable。',
    SESSION_INDEX_REPAIR_FAILED:'Codex 无法补齐会话索引，接入配置尚未切换。请检查 Codex 版本和本地数据后重试。',
    SESSION_INDEX_REPAIR_INCOMPLETE:'Codex 尚未补齐全部会话索引，接入配置尚未切换。请检查会话是否能在 Codex 中读取。',
    SESSION_MODEL_LIST_EMPTY:'缺少可用的官方模型列表，无法替换第三方会话模型。请先更新模型列表。',
    SESSION_BASELINE_UNAVAILABLE:'首次基线缺失或损坏，已停止切换。请退出相关 Codex 客户端，检查备份；确认采用当前状态后，运行 codex-hybrid reset-session-baseline（自定义目录需传 --codex-home 和 --data-dir）重建。',
    SESSION_MIGRATION_RECOVERY_REQUIRED:'发现中断的会话迁移，请按使用文档恢复备份后重试。',
    CLIENT_CONFIG_CHANGED:'Codex 配置在预览后发生变化，或接入字段已被外部修改。未应用切换，请刷新并检查配置后重试。',
    CLIENT_BASELINE_UNAVAILABLE:'缺少可信的接入前配置备份，已停止自动恢复。请检查本地备份后修复。',
    CLIENT_CONFIG_REWRITE_UNSAFE:'无法安全修改 Codex 配置，已停止切换。请检查配置格式。',
    CLIENT_ROUTING_UNAVAILABLE:'当前 Codex 配置无法切换，请检查配置文件、厂商和 profile。',
    CLIENT_ROUTING_ALREADY_SET:'配置已处于目标状态，请刷新查看。'
  };
  if(routingErrors[error.message])return routingErrors[error.message];
  if(error.message==='LOCAL_AUTH_REQUIRED')return '已开启私密链接访问，请运行 codex-hybrid manage-url 获取管理链接。';
  if(error.message==='UPSTREAM_HTTP_401'){
    const source=sourceMode==='cc_switch'?'CC Switch':'独立管理';
    const next=sourceMode==='cc_switch'?'请在 CC Switch 更新该厂商的 API Key，然后重试。':'请在厂商配置中更新 API Key 并保存，然后重试。';
    return '厂商认证失败（401）。当前凭据来源：'+source+'。'+next+'无需重启网关，不会回退到其他 Key。';
  }
  return '操作未完成：'+error.message;
}
