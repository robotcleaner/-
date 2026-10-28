"""
韩国SK文件修复工具 - 专用版本
用于修复韩国SK原始表格.xlsx的格式问题
"""

import pandas as pd
import numpy as np
from pathlib import Path
import os
import re
from datetime import datetime

class SKFileFixer:
    """韩国SK文件修复器专业版"""
    
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.analysis_result = {}
        self.fixed_data = None
        
    def analyze_file(self) -> dict:
        """深度分析文件格式"""
        print(f"分析韩国SK文件: {self.file_path.name}")
        
        try:
            # 1. 读取原始数据（无表头）
            df_raw = pd.read_excel(self.file_path, header=None, nrows=100)
            self.analysis_result['raw_shape'] = df_raw.shape
            
            # 2. 分析行内容
            row_analysis = []
            for i in range(min(50, len(df_raw))):
                row = df_raw.iloc[i]
                non_empty_cells = [(j, str(row[j])[:30]) for j in range(len(row)) 
                                  if pd.notna(row[j]) and str(row[j]).strip() != '']
                
                if non_empty_cells:
                    row_analysis.append({
                        'row': i,
                        'non_empty_count': len(non_empty_cells),
                        'sample_cells': non_empty_cells[:5]
                    })
                    
            self.analysis_result['row_analysis'] = row_analysis[:10]  # 只保留前10行
            
            # 3. 查找可能的表头
            header_candidates = self._find_header_candidates(df_raw)
            self.analysis_result['header_candidates'] = header_candidates
            
            # 4. 检查常见韩文工单关键词
            kr_keywords = ['고장', '수리', '접수', '품질', '장애', '이상', '결함', '보증', 'AS']
            keyword_hits = []
            for i in range(min(20, len(df_raw))):
                row_text = ' '.join(str(x) for x in df_raw.iloc[i].dropna())
                hits = [kw for kw in kr_keywords if kw in row_text]
                if hits:
                    keyword_hits.append({
                        'row': i,
                        'keywords': hits,
                        'text_sample': row_text[:100]
                    })
                    
            self.analysis_result['keyword_hits'] = keyword_hits
            
            print(f"分析完成: {df_raw.shape}")
            return self.analysis_result
            
        except Exception as e:
            print(f"分析失败: {e}")
            return {'error': str(e)}
    
    def _find_header_candidates(self, df: pd.DataFrame) -> list:
        """查找可能的表头行"""
        candidates = []
        
        # 定义表头特征
        header_patterns = ['Claims', 'Service', 'Fee', 'QTY', 'incident', 'charge', 'KRW']
        
        for row_idx in range(min(30, len(df))):
            row = df.iloc[row_idx]
            row_text = ' '.join(str(x) for x in row.dropna())
            
            score = 0
            found_patterns = []
            
            # 检查表头模式
            for pattern in header_patterns:
                if pattern in row_text:
                    score += 10
                    found_patterns.append(pattern)
            
            # 检查是否是较短文本（可能是表头）
            non_empty_vals = [str(v) for v in row.dropna() if str(v).strip()]
            avg_length = np.mean([len(v) for v in non_empty_vals]) if non_empty_vals else 0
            
            if avg_length < 30:
                score += 5
                
            # 检查是否包含数字金额格式
            if any('KRW' in val or '원' in str(val) for val in row.dropna()):
                score += 15
                
            if score > 5:
                candidates.append({
                    'row': row_idx,
                    'score': score,
                    'patterns': found_patterns,
                    'values': non_empty_vals[:5]
                })
        
        # 按分数排序
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates
    
    def fix_file_format(self, target_header_row: int = None) -> pd.DataFrame:
        """修复文件格式"""
        print(f"修复文件格式...")
        
        try:
            # 如果没有指定表头行，自动选择最佳候选
            if target_header_row is None and self.analysis_result.get('header_candidates'):
                best_candidate = self.analysis_result['header_candidates'][0]
                target_header_row = best_candidate['row']
                print(f"自动选择表头行: 第{target_header_row}行")
            
            # 从表头行开始读取
            if target_header_row is not None:
                print(f"从第{target_header_row}行开始读取...")
                data_df = pd.read_excel(self.file_path, skiprows=target_header_row)
                
                # 清理列名
                new_columns = []
                for i, col in enumerate(data_df.columns):
                    if pd.isna(col) or 'Unnamed' in str(col):
                        # 尝试从第一行数据推断列名
                        if len(data_df) > 0 and i < len(data_df.iloc[0]):
                            first_val = data_df.iloc[0, i]
                            if pd.notna(first_val):
                                col_name = f"field_{i}_{str(first_val)[:10]}"
                            else:
                                col_name = f"field_{i}"
                        else:
                            col_name = f"field_{i}"
                        new_columns.append(col_name)
                    else:
                        new_columns.append(str(col))
                
                data_df.columns = new_columns
                
                # 清理数据
                print(f"原始形状: {data_df.shape}")
                
                # 移除完全空的行
                cleaned_df = data_df.dropna(how='all')
                print(f"清理后: {cleaned_df.shape}")
                
                # 移除完全空的列
                empty_cols = cleaned_df.columns[cleaned_df.isna().all()]
                cleaned_df = cleaned_df.drop(columns=empty_cols)
                print(f"移除空列后: {cleaned_df.shape}")
                
                self.fixed_data = cleaned_df
                
                # 保存修复后的文件
                self.save_fixed_file()
                
                return cleaned_df
                
            else:
                print("无法确定表头行位置")
                return None
                
        except Exception as e:
            print(f"修复失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def save_fixed_file(self, output_path: str = None) -> str:
        """保存修复后的文件"""
        if self.fixed_data is None:
            print("没有修复后的数据可以保存")
            return None
            
        if output_path is None:
            output_dir = self.file_path.parent / "修复后_SK"
            output_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"fixed_{self.file_path.stem}_{timestamp}.xlsx"
        
        try:
            self.fixed_data.to_excel(output_path, index=False)
            print(f"修复后的文件已保存: {output_path}")
            return str(output_path)
        except Exception as e:
            print(f"保存失败: {e}")
            return None
    
    def create_analysis_report(self, report_path: str = None) -> str:
        """创建分析报告"""
        if report_path is None:
            output_dir = self.file_path.parent / "修复后_SK"
            output_dir.mkdir(exist_ok=True)
            report_path = output_dir / f"analysis_{self.file_path.stem}.txt"
        
        report_content = f"""
韩国SK文件分析报告
==================
文件: {self.file_path.name}
分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

基本分析:
----------
"""
        
        if 'raw_shape' in self.analysis_result:
            report_content += f"- 原始数据形状: {self.analysis_result['raw_shape']}\n"
        
        report_content += f"""
表头分析:
---------
"""
        if 'header_candidates' in self.analysis_result:
            for cand in self.analysis_result['header_candidates'][:5]:
                report_content += f"第{cand['row']}行 (分数: {cand['score']}): {cand.get('patterns', [])}\n"
                report_content += f"  示例值: {cand.get('values', [])}\n"
        
        if self.fixed_data is not None:
            report_content += f"""
修复结果:
----------
- 修复后形状: {self.fixed_data.shape}
- 修复后列数: {len(self.fixed_data.columns)}
- 前5个列名: {list(self.fixed_data.columns[:5])}

建议:
------
"""
        
        if self.analysis_result.get('keyword_hits'):
            report_content += "1. 文件中发现韩文关键词，可能是韩文工单或费用结算单\n"
        if self.analysis_result.get('header_candidates'):
            best_candidate = self.analysis_result['header_candidates'][0]
            if best_candidate['score'] > 20:
                report_content += f"2. 建议使用第{best_candidate['row']}行作为表头\n"
        
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
            print(f"分析报告已保存: {report_path}")
            return str(report_path)
        except Exception as e:
            print(f"保存报告失败: {e}")
            return None

def main():
    """主函数"""
    print("=== 韩国SK文件修复工具 ===")
    
    # 文件路径
    sk_file = r"C:\Users\admin\.openclaw\workspace\Knowledge\main\1\原始工单\韩国SK原始表格.xlsx"
    
    if not os.path.exists(sk_file):
        print(f"文件不存在: {sk_file}")
        return
    
    # 创建修复器
    fixer = SKFileFixer(sk_file)
    
    # 1. 分析文件
    print("\n1. 分析文件格式...")
    analysis = fixer.analyze_file()
    
    if 'error' in analysis:
        print(f"分析失败: {analysis['error']}")
        return
    
    # 2. 修复文件
    print("\n2. 修复文件格式...")
    fixed_df = fixer.fix_file_format()
    
    if fixed_df is not None:
        print(f"\n修复成功!")
        print(f"原始形状: {analysis.get('raw_shape', 'N/A')}")
        print(f"修复形状: {fixed_df.shape}")
        print(f"修复列名: {list(fixed_df.columns)[:10]}")
        
        # 3. 保存分析报告
        print("\n3. 生成分析报告...")
        fixer.create_analysis_report()
        
        print(f"\n✅ 韩国SK文件修复完成!")
    else:
        print(f"\n❌ 修复失败")

if __name__ == "__main__":
    main()