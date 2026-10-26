"""
韩国SK原始工单格式诊断工具
用于分析和修复韩国SK原始工单的格式问题
"""

import pandas as pd
import numpy as np
from pathlib import Path
import re
import json
from typing import Dict, List, Tuple, Optional

class SKFormatDiagnoser:
    """韩国SK原始工单格式诊断器"""
    
    def __init__(self, raw_sk_path: str = None):
        self.raw_path = raw_sk_path
        self.diagnosis_results = {}
        
    def run_full_diagnosis(self) -> Dict:
        """运行完整诊断"""
        print("=== 韩国SK原始工单格式诊断开始 ===")
        
        if not self.raw_path or not Path(self.raw_path).exists():
            raise FileNotFoundError(f"文件不存在: {self.raw_path}")
        
        # 1. 基础文件信息
        self.diagnosis_results['file_info'] = self._get_file_info()
        
        # 2. 分析工作表结构
        self.diagnosis_results['sheet_info'] = self._analyze_sheets()
        
        # 3. 自动探测正确的读取方式
        self.diagnosis_results['read_methods'] = self._auto_detect_best_read_method()
        
        # 4. 内容模式分析
        self.diagnosis_results['content_patterns'] = self._analyze_content_patterns()
        
        # 5. 与处理器配置匹配分析
        self.diagnosis_results['config_compatibility'] = self._check_config_compatibility()
        
        # 6. 生成修复建议
        self.diagnosis_results['fix_suggestions'] = self._generate_fix_suggestions()
        
        print("=== 诊断完成 ===")
        return self.diagnosis_results
    
    def _get_file_info(self) -> Dict:
        """获取文件基础信息"""
        path = Path(self.raw_path)
        return {
            'filename': path.name,
            'size_bytes': path.stat().st_size,
            'last_modified': path.stat().st_mtime,
            'suffix': path.suffix
        }
    
    def _analyze_sheets(self) -> Dict:
        """分析Excel工作表"""
        try:
            excel_file = pd.ExcelFile(self.raw_path)
            sheets = excel_file.sheet_names
            sheet_info = {
                'total_sheets': len(sheets),
                'sheet_names': sheets,
                'recommended_sheet': self._find_data_sheet(excel_file, sheets)
            }
            
            # 分析每个工作表
            for sheet in sheets:
                try:
                    df_sample = pd.read_excel(self.raw_path, sheet_name=sheet, nrows=10)
                    sheet_info[f'{sheet}_sample'] = {
                        'rows': len(df_sample),
                        'cols': len(df_sample.columns),
                        'first_rows': df_sample.head(3).to_dict('records')
                    }
                except Exception as e:
                    sheet_info[f'{sheet}_error'] = str(e)
            
            return sheet_info
        except Exception as e:
            return {'error': str(e)}
    
    def _find_data_sheet(self, excel_file, sheets: List[str]) -> str:
        """找到包含工单数据的工作表"""
        data_keywords = ['data', '工单', '接单', 'repair', '수리', '접수']
        for sheet in sheets:
            if any(keyword in sheet.lower() for keyword in data_keywords):
                return sheet
        return sheets[0]  # 默认返回第一个工作表
    
    def _auto_detect_best_read_method(self) -> Dict:
        """自动探测最佳读取方式"""
        methods = []
        
        for skip_rows in range(0, 12):
            try:
                df = pd.read_excel(self.raw_path, skiprows=skip_rows, nrows=10)
                if len(df) > 3:  # 有足够数据
                    valid_header = self._evaluate_header_row(df)
                    if valid_header['is_valid']:
                        methods.append({
                            'skip_rows': skip_rows,
                            'valid_header': valid_header,
                            'sample_columns': list(df.columns)[:10]
                        })
            except Exception as e:
                continue
        
        return {
            'total_methods_found': len(methods),
            'methods': methods,
            'recommended_method': self._select_best_method(methods)
        }
    
    def _evaluate_header_row(self, df: pd.DataFrame) -> Dict:
        """评估表头行的质量"""
        if len(df.columns) == 0:
            return {'is_valid': False, 'reason': '无列'}
        
        # 检查Unnamed列的比例
        unnamed_count = sum(1 for col in df.columns if str(col).startswith('Unnamed'))
        unnamed_ratio = unnamed_count / len(df.columns) if len(df.columns) > 0 else 1
        
        # 检查是否有常见的关键词
        common_keywords = ['접수', 'SN', '모델', '고장', '수리', '일자', 'Ticket', 'Serial', 'Model']
        found_keywords = []
        for col in df.columns:
            col_str = str(col)
            for keyword in common_keywords:
                if keyword in col_str:
                    found_keywords.append(keyword)
        
        return {
            'is_valid': unnamed_ratio < 0.5 and len(found_keywords) > 0,
            'unnamed_ratio': unnamed_ratio,
            'found_keywords': list(set(found_keywords)),
            'total_columns': len(df.columns)
        }
    
    def _select_best_method(self, methods: List[Dict]) -> Optional[Dict]:
        """选择最佳读取方法"""
        if not methods:
            return None
        
        # 评分标准: 有效的关键词越多越好, Unnamed列越少越好
        scored = []
        for method in methods:
            valid_info = method['valid_header']
            score = (
                len(valid_info['found_keywords']) * 10 -
                valid_info['unnamed_ratio'] * 100 +
                valid_info['total_columns'] * 0.1
            )
            scored.append((score, method))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else None
    
    def _analyze_content_patterns(self) -> Dict:
        """分析内容模式"""
        try:
            # 尝试用最佳方法读取数据
            best_method = self.diagnosis_results['read_methods']['recommended_method']
            if not best_method:
                return {'error': '未找到合适的读取方法'}
            
            skip_rows = best_method['skip_rows']
            df = pd.read_excel(self.raw_path, skiprows=skip_rows, nrows=50)
            
            # 查找工单号模式
            ticket_patterns = [
                r'\d{8,}',  # 8位以上的数字
                r'[A-Z]{2,}\d{5,}',  # 字母+数字的模式
                r'KR\d{6,}'  # KR+数字
            ]
            
            ticket_columns = []
            for col in df.columns:
                try:
                    sample = df[col].dropna().astype(str).head(20)
                    for pattern in ticket_patterns:
                        matching = sample.str.contains(pattern, regex=True)
                        if matching.any():
                            ticket_columns.append({
                                'column': col,
                                'pattern_matched': pattern,
                                'sample_values': sample.head(3).tolist()
                            })
                            break
                except:
                    continue
            
            # 查找SN模式
            sn_patterns = [r'[A-Z0-9]{10,}', r'SN\d{8,}']
            sn_columns = []
            
            return {
                'ticket_columns': ticket_columns,
                'sn_columns': sn_columns,
                'data_sample_shape': f'{len(df)}x{len(df.columns)}'
            }
        except Exception as e:
            return {'error': str(e)}
    
    def _check_config_compatibility(self) -> Dict:
        """检查与现有配置的兼容性"""
        from config_kr import COLUMN_MAP_KR
        
        issues = []
        matched = []
        
        if 'read_methods' in self.diagnosis_results:
            best_method = self.diagnosis_results['read_methods']['recommended_method']
            if best_method:
                skip_rows = best_method['skip_rows']
                try:
                    df = pd.read_excel(self.raw_path, skiprows=skip_rows, nrows=10)
                    
                    # 检查哪些配置列名能在文件中找到
                    config_columns = COLUMN_MAP_KR.keys()
                    file_columns = df.columns
                    
                    for config_col in config_columns:
                        found = any(config_col in str(file_col) for file_col in file_columns)
                        if found:
                            matched.append(config_col)
                        else:
                            issues.append({
                                'config_column': config_col,
                                'issue': '在文件中未找到对应列',
                                'recommendation': '检查原始文件是否有该字段'
                            })
                except Exception as e:
                    issues.append({'error': str(e)})
        
        return {
            'config_columns_total': len(COLUMN_MAP_KR),
            'matched_columns': matched,
            'unmatched_columns': issues,
            'match_rate': len(matched) / len(COLUMN_MAP_KR) if COLUMN_MAP_KR else 0
        }
    
    def _generate_fix_suggestions(self) -> Dict:
        """生成修复建议"""
        suggestions = []
        
        comp = self.diagnosis_results.get('config_compatibility', {})
        match_rate = comp.get('match_rate', 0)
        
        if match_rate < 0.3:
            suggestions.append(
                "严重不匹配：原始文件可能与当前韩国配置完全不符。建议："
                "1. 检查是否上传了错误的原始文件\n"
                "2. 检查原始文件的表头结构是否变化\n"
                "3. 可能需要手工指定列映射规则"
            )
        
        if self.diagnosis_results.get('content_patterns', {}).get('ticket_columns'):
            suggestions.append(
                f"检测到工单号列: {self.diagnosis_results['content_patterns']['ticket_columns']}"
            )
        
        # 最佳读取方法建议
        best_method = self.diagnosis_results['read_methods']['recommended_method']
        if best_method:
            suggestions.append(
                f"✅ 推荐读取方法：跳过{best_method['skip_rows']}行作为表头"
            )
        
        return suggestions
    
    def save_diagnosis_report(self, output_path: str = None):
        """保存诊断报告"""
        if not output_path:
            output_path = Path(self.raw_path).parent / f"diagnosis_{Path(self.raw_path).stem}.json"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.diagnosis_results, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"诊断报告已保存至: {output_path}")
        return output_path
    
    def create_fix_config(self, output_path: str = None):
        """创建修复配置"""
        best_method = self.diagnosis_results['read_methods']['recommended_method']
        if not best_method:
            return None
        
        fix_config = {
            'raw_file_path': self.raw_path,
            'recommended_read_method': {
                'skip_rows': best_method['skip_rows'],
                'header_row_index': best_method['skip_rows']
            },
            'detected_issues': self.diagnosis_results['config_compatibility'].get('unmatched_columns', []),
            'detected_columns': {
                'ticket_columns': self.diagnosis_results['content_patterns'].get('ticket_columns', []),
                'sn_columns': self.diagnosis_results['content_patterns'].get('sn_columns', [])
            },
            'created_at': pd.Timestamp.now().isoformat(),
            'diagnosis_version': '1.0'
        }
        
        if not output_path:
            output_path = Path(self.raw_path).parent / f"fix_config_{Path(self.raw_path).stem}.json"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(fix_config, f, ensure_ascii=False, indent=2, default=str)
        
        return output_path


def diagnose_sk_file(raw_file_path: str):
    """诊断韩国SK原始文件的快速入口函数"""
    diagnoser = SKFormatDiagnoser(raw_file_path)
    results = diagnoser.run_full_diagnosis()
    
    # 输出摘要
    print("\n" + "="*60)
    print("✅ 诊断摘要")
    print("="*60)
    
    if 'file_info' in results:
        print(f"📄 文件: {results['file_info']['filename']} ({results['file_info']['size_bytes']:,} bytes)")
    
    if 'read_methods' in results and results['read_methods']['recommended_method']:
        method = results['read_methods']['recommended_method']
        print(f"⚙️  推荐读取: 跳过{method['skip_rows']}行作为表头")
        print(f"📊 检测到列: {', '.join(method['sample_columns'][:5])}")
    
    if 'config_compatibility' in results:
        comp = results['config_compatibility']
        print(f"🔧 配置兼容性: {comp.get('matched_columns', [])} 列匹配")
        print(f"⚠️  配置不匹配: {len(comp.get('unmatched_columns', []))} 列")
    
    if 'fix_suggestions' in results:
        print(f"💡 建议: {len(results['fix_suggestions'])} 条建议")
        for i, suggestion in enumerate(results['fix_suggestions'], 1):
            print(f"   {i}. {suggestion[:100]}...")
    
    # 保存报告
    report_path = diagnoser.save_diagnosis_report()
    config_path = diagnoser.create_fix_config()
    
    return {
        'diagnosis_results': results,
        'report_path': report_path,
        'fix_config_path': config_path
    }


if __name__ == "__main__":
    # 测试诊断
    import sys
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = "../原始工单/韩国SK原始表格.xlsx"
    
    diagnose_sk_file(file_path)