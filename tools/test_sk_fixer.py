"""
韩国SK修复工具测试脚本
"""

import pandas as pd
import numpy as np
from pathlib import Path
import os

def test_sk_file_fix():
    """测试韩国SK文件修复"""
    print("=== 第一步：韩国SK文件修复工具测试 ===")
    
    # 文件路径
    sk_file = r"C:\Users\admin\.openclaw\workspace\Knowledge\main\1\原始工单\韩国SK原始表格.xlsx"
    print(f"测试文件: {os.path.basename(sk_file)}")
    
    if not os.path.exists(sk_file):
        print("❌ 文件不存在")
        return
    
    print("1. 分析文件基本信息...")
    
    try:
        # 读取文件原始格式
        print("  尝试读取原始格式...")
        df = pd.read_excel(sk_file, header=None, nrows=50)
        print(f"  读取成功: {df.shape[0]} 行, {df.shape[1]} 列")
        print(f"  总单元格数: {df.size}")
        
        # 统计空值情况
        empty_count = df.isna().sum().sum()
        print(f"  空单元格数: {empty_count} ({empty_count/df.size:.1%})")
        
        # 检查数据类型
        print("  数据类型统计:")
        numeric_count = df.applymap(lambda x: isinstance(x, (int, float))).sum().sum()
        text_count = df.applymap(lambda x: isinstance(x, str)).sum().sum()
        print(f"    数值类型: {numeric_count}")
        print(f"    文本类型: {text_count}")
        
        print("\n2. 检查文件结构问题...")
        
        # 检查Unnamed列问题
        print("  寻找可能的表头行...")
        header_candidates = []
        max_check = min(30, len(df))
        
        header_keywords = ['Claims', 'Service', 'Fee', 'KRW', 'QTY', 'incident', 'charge']
        
        for row_idx in range(max_check):
            row = df.iloc[row_idx]
            row_text = ' '.join([str(v) for v in row.dropna() if str(v).strip()])
            
            keyword_matches = sum(1 for kw in header_keywords if kw in row_text)
            non_empty = row.notna().sum()
            
            if keyword_matches > 0 or non_empty >= 4:
                header_candidates.append({
                    'row': row_idx,
                    'keywords': keyword_matches,
                    'non_empty': non_empty,
                    'content': row_text[:100]
                })
        
        if header_candidates:
            print(f"  找到 {len(header_candidates)} 个可能的表头行")
            print("  最佳候选:")
            for cand in header_candidates[:3]:
                print(f"    第{cand['row']}行: {cand['keywords']}个关键词, {cand['non_empty']}个非空")
                print(f"      内容: {cand['content'][:80]}...")
        else:
            print("  未找到明显的表头行")
        
        print("\n3. 提取实际内容...")
        
        # 尝试从可能的表头开始读取
        if header_candidates:
            header_row = header_candidates[0]['row']
            print(f"  从第{header_row}行开始重新读取...")
            
            try:
                df_with_header = pd.read_excel(sk_file, skiprows=header_row, nrows=100)
                print(f"  重新读取成功: {df_with_header.shape[0]} 行, {df_with_header.shape[1]} 列")
                
                # 清理列名
                new_columns = []
                for i, col in enumerate(df_with_header.columns):
                    if pd.isna(col) or str(col).startswith('Unnamed'):
                        new_columns.append(f'field_{i}')
                    else:
                        new_columns.append(str(col))
                
                df_with_header.columns = new_columns
                
                print("\n  修复后列名:")
                for i, col in enumerate(df_with_header.columns[:15], 1):
                    non_null = df_with_header[col].notna().sum()
                    print(f"    {i:2d}. {col}: {non_null} 非空")
                
                print("\n  数据示例:")
                if len(df_with_header) > 0:
                    first_row = df_with_header.iloc[0]
                    for i in range(min(8, len(first_row))):
                        val = first_row[i]
                        if pd.notna(val):
                            print(f"    字段{i}: {str(val)[:30]}")
                
                # 保存修复后的文件
                output_dir = Path(sk_file).parent / "修复后"
                output_dir.mkdir(exist_ok=True)
                output_path = output_dir / f"fixed_kr_sk_{Path(sk_file).stem}.xlsx"
                
                df_cleaned = df_with_header.dropna(how='all')
                
                if not df_cleaned.empty:
                    df_cleaned.to_excel(output_path, index=False)
                    print(f"\n✅ 修复成功!")
                    print(f"   原始数据: {df.shape}")
                    print(f"   修复后数据: {df_cleaned.shape}")
                    print(f"   保存路径: {output_path}")
                else:
                    print("\n⚠️ 提取的数据为空")
                    
            except Exception as e:
                print(f"  重新读取失败: {e}")
                
        else:
            print("  无法确定表头位置")
        
        print("\n✅ 韩国SK文件修复测试完成")
        
    except Exception as e:
        print(f"❌ 测试过程出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sk_file_fix()