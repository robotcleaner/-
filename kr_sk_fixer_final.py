"""
韩国SK文件修复工具 - 最终版
处理Unicode编码问题并修复文件格式
"""

import pandas as pd
import os
from pathlib import Path
import sys

def fix_kr_sk_file():
    """修复韩国SK文件的主函数"""
    print("=== 韩国SK文件修复工具运行 ===")
    
    # 文件路径
    sk_file = r"C:\Users\admin\.openclaw\workspace\Knowledge\main\1\原始工单\韩国SK原始表格.xlsx"
    print(f"目标文件: {sk_file}")
    
    if not os.path.exists(sk_file):
        print("❌ 文件不存在")
        return
    
    print("1. 分析文件基本信息...")
    
    try:
        # 首先检查文件属性
        file_size = os.path.getsize(sk_file)
        print(f"   文件大小: {file_size:,} bytes")
        
        # 读取前几行（不带表头）
        print("   读取原始格式...")
        df_raw = pd.read_excel(sk_file, header=None, engine='openpyxl', nrows=15)
        print(f"   读取成功: {df_raw.shape}")
        
        print("\n2. 显示原始内容（安全编码）...")
        
        # 安全显示内容，避免编码问题
        row_count = min(8, len(df_raw))
        col_count = min(10, len(df_raw.columns))
        
        for i in range(row_count):
            values = []
            for j in range(col_count):
                val = df_raw.iat[i, j]
                if pd.isna(val):
                    values.append("[空]")
                else:
                    # 安全处理字符串
                    try:
                        val_str = str(val)
                        # 截断长字符串
                        if len(val_str) > 20:
                            val_str = val_str[:20] + "..."
                        values.append(val_str)
                    except:
                        values.append("[编码错误]")
            
            # 只显示有内容的行
            if any(v != "[空]" for v in values):
                print(f"   行{i}: {values}")
        
        print("\n3. 查找表头行...")
        
        # 查找包含关键词的行
        header_keywords = ['Claims', 'Service', 'Fee', 'QTY', 'incident', 'charge', 'KRW']
        header_candidates = []
        
        for row_idx in range(min(15, len(df_raw))):
            row = df_raw.iloc[row_idx]
            non_empty_count = 0
            keyword_hits = 0
            
            for val in row:
                if pd.notna(val):
                    non_empty_count += 1
                    val_str = str(val)
                    for kw in header_keywords:
                        if kw in val_str:
                            keyword_hits += 1
            
            if keyword_hits > 0 or non_empty_count >= 3:
                header_candidates.append({
                    'row': row_idx,
                    'keywords': keyword_hits,
                    'non_empty': non_empty_count
                })
        
        if header_candidates:
            print(f"   找到 {len(header_candidates)} 个候选表头行")
            best_candidate = header_candidates[0]
            print(f"   最佳候选: 第{best_candidate['row']}行 (关键词: {best_candidate['keywords']}, 非空: {best_candidate['non_empty']})")
        else:
            print("   未找到明显的表头行")
            best_candidate = {'row': 0, 'keywords': 0, 'non_empty': 0}
        
        print("\n4. 尝试修复文件...")
        
        # 创建输出目录
        output_dir = Path(sk_file).parent / "修复结果"
        output_dir.mkdir(exist_ok=True)
        
        # 方法1: 跳过表头行读取
        skip_rows = best_candidate['row']
        if skip_rows > 0:
            print(f"   方法1: 跳过{skip_rows}行读取...")
            
            try:
                df_fixed = pd.read_excel(sk_file, skiprows=skip_rows, engine='openpyxl')
                print(f"      读取成功: {df_fixed.shape}")
                
                # 清理列名
                new_columns = []
                for i, col in enumerate(df_fixed.columns):
                    if pd.isna(col) or 'Unnamed' in str(col):
                        new_columns.append(f"字段_{i}")
                    else:
                        col_str = str(col)
                        # 简单清理列名
                        col_str = col_str.strip()
                        if len(col_str) > 30:
                            col_str = col_str[:30]
                        new_columns.append(col_str)
                
                df_fixed.columns = new_columns
                
                # 清理空行
                df_cleaned = df_fixed.dropna(how='all')
                print(f"      清理空行后: {df_cleaned.shape}")
                
                # 清理空列
                empty_cols = df_cleaned.columns[df_cleaned.isna().all()]
                df_cleaned = df_cleaned.drop(columns=empty_cols)
                print(f"      清理空列后: {df_cleaned.shape}")
                
                if not df_cleaned.empty:
                    # 生成输出文件名
                    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
                    output_file = output_dir / f"fixed_kr_sk_{timestamp}.xlsx"
                    
                    # 保存修复后的文件
                    df_cleaned.to_excel(output_file, index=False)
                    
                    print(f"\n✅ 修复成功!")
                    print(f"   原始文件: {sk_file}")
                    print(f"   原始形状: {df_raw.shape}")
                    print(f"   修复后形状: {df_cleaned.shape}")
                    print(f"   输出文件: {output_file}")
                    
                    # 显示修复后的列名
                    print(f"\n修复后列名: {list(df_cleaned.columns)[:12]}")
                    
                    # 显示几行数据
                    if len(df_cleaned) > 0:
                        print("\n修复数据示例:")
                        for i in range(min(3, len(df_cleaned))):
                            row_vals = []
                            for val in df_cleaned.iloc[i].values[:5]:
                                if pd.isna(val):
                                    row_vals.append("[空]")
                                else:
                                    val_str = str(val)
                                    if len(val_str) > 15:
                                        val_str = val_str[:15] + "..."
                                    row_vals.append(val_str)
                            print(f"   行{i}: {row_vals}")
                    
                    return True
                else:
                    print("❌ 修复后数据为空")
                    
            except Exception as e:
                print(f"   方法1失败: {e}")
        
        # 方法2: 原始读取
        print("\n   方法2: 尝试原始读取...")
        try:
            df_simple = pd.read_excel(sk_file, engine='openpyxl')
            print(f"      读取成功: {df_simple.shape}")
            
            if len(df_simple.columns) > 3:
                output_file = output_dir / "simple_fixed_kr_sk.xlsx"
                df_simple.to_excel(output_file, index=False)
                print(f"      保存到: {output_file}")
        
        except Exception as e:
            print(f"   方法2失败: {e}")
        
        return False
        
    except Exception as e:
        print(f"❌ 修复过程失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主程序"""
    print("开始修复韩国SK文件...")
    print("=" * 40)
    
    success = fix_kr_sk_file()
    
    print("\n" + "=" * 40)
    if success:
        print("✅ 修复任务完成!")
    else:
        print("❌ 修复任务失败")
    
    print("\n注：修复后的文件保存在'修复结果'目录中")
    print("可以进行进一步的处理或验证")

if __name__ == "__main__":
    # 设置编码
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()