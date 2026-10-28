"""
澳洲区域配置优化方案
针对10月上原始工单AU.xlsx的实际列名调整
"""

# ===== 澳洲原始表 → 输出表的列映射（针对10月上表格）=====
COLUMN_MAP_AU_OPTIMIZED = {
    # 基础信息字段
    "Ticket Number":                            "工单号",
    "Serial Number":                            "SN",
    
    # 设备信息
    "Device Name":                              "设备名称",
    
    # 故障描述（实际文件中列为Customer Complaint）
    "Customer Complaint":                       "用户描述原文",
    
    # 质保信息
    "Ticket Type":                              "质保",
    "Type of Service":                          "Type of Service原值",
    
    # 故障分类（注意：实际列名包含中文字符）
    "Fault Classification 1 故障类别 1":        "Fault_Classification_1",
    "Fault Classification 2 故障类别 2":        "Fault_Classification_2", 
    "Fault Classification 3 故障类别 3":        "Fault_Classification_3",
    
    # 维修信息
    "Service Level":                            "Service Level",
    "Repair Start Date 开始维修日期":            "Repair_Start_Date",
    "Repair Details 维修方案":                   "Repair_Details",
    "Repair Details (Technician Notes)":        "Repair_Details_Technician_Notes",
    
    # 备件信息
    "SKU consumption 备件使用":                  "SKU_consumption",
    
    # 辅助字段（实际列名包含中文冒号）
    "Auxiliary Field：Status":                  "Status",
    "Auxiliary Field：Received  Date 2":        "Received_Date_2",  
    "Auxiliary Field：Repair TAT":              "Repair_TAT",
    "Auxiliary Field：Repair SLA":              "Repair_SLA",
    "Auxiliary Field：DOA Validation":          "DOA_Validation",
    "Auxiliary Field：Product Type":            "Product_Type",
    
    # 日期字段
    "Date Created":                             "创建日期",
    "Date Purchased":                           "购买日期",
    "Auxiliary Field：Closed Date":             "关单日期",
}

# ===== 列名模糊匹配规则（用于自动映射）=====
COLUMN_PATTERN_RULES = {
    # 按优先级匹配
    "ticket.*number": "Ticket Number",
    "serial.*number": "Serial Number",
    "customer.*complaint": "Customer Complaint",
    "device.*name": "Device Name",
    "fault.*classification.*1.*故障": "Fault Classification 1 故障类别 1",
    "fault.*classification.*2.*故障": "Fault Classification 2 故障类别 2", 
    "fault.*classification.*3.*故障": "Fault Classification 3 故障类别 3",
    "repair.*start.*date": "Repair Start Date 开始维修日期",
    "repair.*details.*维修": "Repair Details 维修方案",
    "sku.*consumption": "SKU consumption 备件使用",
}

# ===== 字段提取转换函数 =====
def generate_field_extractor(actual_file_path):
    """
    根据实际文件智能生成字段提取器
    """
    import pandas as pd
    import re
    
    # 读取文件前几行获取列名
    df_sample = pd.read_excel(actual_file_path, nrows=5)
    actual_columns = list(df_sample.columns)
    
    extractor_config = {}
    
    for pattern, target in COLUMN_PATTERN_RULES.items():
        regex = re.compile(pattern, re.IGNORECASE)
        for col in actual_columns:
            if regex.search(col):
                extractor_config[target] = col
                break
    
    return extractor_config

# ===== 测试函数 =====
def test_au_config_compatibility():
    """测试配置兼容性"""
    print("=== 澳洲区域配置兼容性测试 ===")
    
    test_file = r"C:\Users\admin\.openclaw\workspace\Knowledge\main\1\原始工单\10月上原始工单AU.xlsx"
    
    try:
        df = pd.read_excel(test_file, nrows=5)
        print(f"文件读取成功: {len(df.columns)} 列")
        
        extractor = generate_field_extractor(test_file)
        print(f"生成了 {len(extractor)} 个字段映射:")
        
        for target_col, actual_col in extractor.items():
            print(f"  {target_col} → {actual_col}")
            
        # 检查关键字段
        key_fields = ["Ticket Number", "Serial Number", "Customer Complaint", 
                     "Fault Classification 1 故障类别 1", "Repair Start Date 开始维修日期"]
        
        print(f"\n关键字段检查:")
        for field in key_fields:
            if field in extractor:
                actual_col = extractor[field]
                if actual_col in df.columns:
                    value = df[actual_col].iloc[0] if not pd.isna(df[actual_col].iloc[0]) else "空值"
                    print(f"  ✓ {field}: 匹配成功 (示例: {str(value)[:30]})")
                else:
                    print(f"  ✗ {field}: 配置映射失败")
            else:
                print(f"  ? {field}: 未找到配置映射")
                
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        return False

if __name__ == "__main__":
    import pandas as pd
    test_au_config_compatibility()