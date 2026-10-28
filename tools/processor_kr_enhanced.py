"""
增强版韩国SK工单处理器
具备自动格式探测、智能映射和容错处理功能
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import re
import json
from typing import Dict, List, Tuple, Optional, Union
import warnings

from config_kr import (
    COLUMN_MAP_KR, OUTPUT_COLUMNS_KR,
    FIXED_REGION_KR, FIXED_AGENT_KR,
    PRODUCT_CATEGORY_KR,
    WARRANTY_TRUE_KR, WARRANTY_FALSE_KR,
    SKU_COLUMNS_KR,
    KR_TO_CN_FAULT,
    PROCESS_RESULT_KR_MAP, PROCESS_RESULT_FIXED,
    KR_PROMPT_TRANSLATE,
    KR_PROMPT_FAULT_FROM_TEXT,
    KR_PROMPT_PROCESS_RESULT,
)
from llm_client import _call_llm, MODEL_TRANSLATE, MODEL_CLASSIFY


class SKFileAnalyzer:
    """韩国SK文件智能分析器"""
    
    def __init__(self):
        self.analysis_result = {}
        
    def analyze_file(self, file_path: Union[str, Path]) -> Dict:
        """分析韩国SK原始文件"""
        file_path = Path(file_path)
        print(f"正在分析韩国SK文件: {file_path.name}")
        
        try:
            # 1. 读取Excel文件，不设表头
            df_raw = pd.read_excel(file_path, header=None, nrows=30)
            raw_shape = df_raw.shape
            print(f"读取到原始形状: {raw_shape}")
            
            # 2. 自动探测表头位置
            header_row = self._detect_header_row(df_raw)
            print(f"检测到表头行: 第{header_row}行")
            
            # 从表头行开始读取数据
            df = pd.read_excel(file_path, skiprows=header_row)
            
            # 3. 标准化列名
            df_normalized = self._normalize_columns(df)
            
            # 4. 识别关键字段
            field_mapping = self._identify_fields(df_normalized)
            
            # 5. 检查与配置的兼容性
            compatibility = self._check_config_compatibility(df_normalized)
            
            self.analysis_result = {
                'file_name': file_path.name,
                'file_size': file_path.stat().st_size,
                'raw_shape': raw_shape,
                'header_row': header_row,
                'data_shape': df_normalized.shape,
                'columns_count': len(df_normalized.columns),
                'column_names': list(df_normalized.columns),
                'field_mapping': field_mapping,
                'config_compatibility': compatibility,
                'sample_data': df_normalized.head(3).to_dict('records')
            }
            
            print(f"分析完成: {len(df_normalized)}行, {len(df_normalized.columns)}列")
            return self.analysis_result
            
        except Exception as e:
            print(f"分析失败: {e}")
            return {'error': str(e)}
    
    def _detect_header_row(self, df: pd.DataFrame) -> int:
        """自动探测表头行"""
        max_score = -1
        best_row = 0
        
        # 检查每一行作为表头的可能性
        for row_idx in range(min(15, len(df))):
            row = df.iloc[row_idx]
            # 计算这一行作为表头的得分
            score = self._calc_header_score(row)
            if score > max_score:
                max_score = score
                best_row = row_idx
        
        return best_row
    
    def _calc_header_score(self, row) -> float:
        """计算某一行作为表头的得分"""
        score = 0.0
        
        # 1. 有效值数量（非空值）
        non_nan_count = sum(1 for cell in row if pd.notna(cell) and str(cell).strip() != '')
        score += non_nan_count * 5.0
        
        # 2. 包含常见表头关键词
        header_keywords = ['접수', '接单', '工单', 'Ticket', 'SN', 'Serial', 
                          '모델', 'Model', '型号', '일자', 'Date', '日期',
                          '고장', '故障', 'Fault', '수리', '维修', 'Repair',
                          '처리', '结果', 'Result', '품목', '备件', 'Part']
        for cell in row:
            if pd.notna(cell):
                cell_str = str(cell)
                for keyword in header_keywords:
                    if keyword in cell_str:
                        score += 3.0
                        break
        
        # 3. 不包含数据特征（如纯数字ID、日期等）
        data_patterns = [r'^\d{8,}$', r'^\d{4}-\d{2}-\d{2}$', r'^[A-Z0-9]{10,}$']
        for cell in row:
            if pd.notna(cell):
                cell_str = str(cell)
                for pattern in data_patterns:
                    if re.match(pattern, cell_str):
                        score -= 2.0
                        break
        
        return score
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化列名"""
        df_normalized = df.copy()
        new_columns = []
        
        for i, col in enumerate(df.columns):
            if pd.isna(col) or str(col).strip() == '':
                new_name = f'Column_{i+1}'
            else:
                # 清理列名，移除Unnamed前缀
                new_name = str(col).replace('Unnamed:', '').strip()
                if new_name.startswith('Unnamed'):
                    new_name = f'Column_{i+1}'
            
            new_columns.append(new_name)
        
        df_normalized.columns = new_columns
        return df_normalized
    
    def _identify_fields(self, df: pd.DataFrame) -> Dict:
        """智能识别字段"""
        field_map = {}
        
        # 定义字段匹配规则
        field_patterns = {
            '工单号': [r'接.*号', r'접.*号', r'Ticket', r'工单'],
            'SN': [r'SN', r'Serial', r'시리얼', r'序列'],
            '型号': [r'모델', r'Model', r'型号'],
            '日期': [r'일자', r'Date', r'日期'],
            '故障描述': [r'고장', r'Fault', r'故障', r'描述'],
            '维修详情': [r'수리', r'Repair', r'维修'],
            '处理结果': [r'처리', r'Result', r'结果'],
            '备件消耗': [r'품목', r'Part', r'备件', r'消耗'],
        }
        
        for col in df.columns:
            col_str = str(col)
            for field_name, patterns in field_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, col_str, re.IGNORECASE):
                        field_map[field_name] = col
                        break
                if field_name in field_map:
                    break
        
        # 如果未识别到工单号，寻找可能是工单号的列
        if '工单号' not in field_map:
            ticket_candidates = []
            for col in df.columns:
                if df[col].dtype in [np.int64, np.float64]:
                    # 检查是否是长数字
                    sample = df[col].dropna().astype(str).head(10)
                    if all(len(str(val)) >= 6 for val in sample):
                        ticket_candidates.append(col)
                elif df[col].dtype == object:
                    # 检查是否有数字模式
                    sample = df[col].dropna().astype(str).head(10)
                    pattern_count = sum(1 for val in sample if re.match(r'^\d{6,}$', val))
                    if pattern_count > 0:
                        ticket_candidates.append(col)
            
            if ticket_candidates:
                field_map['工单号'] = ticket_candidates[0]
        
        return field_map
    
    def _check_config_compatibility(self, df: pd.DataFrame) -> Dict:
        """检查与config_kr的兼容性"""
        compatibility = {
            'matched': [],
            'unmatched': [],
            'total_config_columns': len(COLUMN_MAP_KR),
            'match_rate': 0.0
        }
        
        config_columns = list(COLUMN_MAP_KR.keys())
        file_columns = list(df.columns)
        
        for config_col in config_columns:
            found = False
            for file_col in file_columns:
                if config_col in str(file_col):
                    compatibility['matched'].append({
                        'config': config_col,
                        'file': file_col,
                        'match_type': 'exact'
                    })
                    found = True
                    break
            
            if not found:
                compatibility['unmatched'].append(config_col)
        
        if config_columns:
            compatibility['match_rate'] = len(compatibility['matched']) / len(config_columns)
        
        return compatibility


class SKDataTransformer:
    """韩国SK数据转换器"""
    
    def __init__(self, analyzer: SKFileAnalyzer = None):
        self.analyzer = analyzer or SKFileAnalyzer()
        self.custom_mapping = {}
        
    def create_custom_mapping(self, df: pd.DataFrame, analysis_result: Dict) -> Dict:
        """创建自定义列映射"""
        field_map = analysis_result.get('field_mapping', {})
        
        # 从分析结果创建映射
        mapping = {}
        
        # 基础字段映射
        if '工单号' in field_map:
            mapping[field_map['工单号']] = '工单号'
        if 'SN' in field_map:
            mapping[field_map['SN']] = 'SN'
        if '型号' in field_map:
            mapping[field_map['型号']] = '型号'
        if '日期' in field_map:
            mapping[field_map['日期']] = '最终处理日'
        if '故障描述' in field_map:
            mapping[field_map['故障描述']] = '用户描述韩文'
        if '维修详情' in field_map:
            mapping[field_map['维修详情']] = '维修详情韩文'
        if '处理结果' in field_map:
            mapping[field_map['处理结果']] = '处理结果3韩文'
        
        # 尝试匹配其他config_kr字段
        for config_col in COLUMN_MAP_KR:
            if config_col not in mapping.values():
                # 在列中寻找匹配
                for file_col in df.columns:
                    if config_col in str(file_col):
                        mapping[file_col] = config_col
                        break
        
        self.custom_mapping = mapping
        return mapping
    
    def transform_dataframe(self, df: pd.DataFrame, custom_mapping: Dict) -> Dict:
        """转换数据格式，输出标准字段"""
        transformed = {}
        
        # 应用自定义映射
        for file_col, target_field in custom_mapping.items():
            if file_col in df.columns:
                transformed[target_field] = df[file_col].iloc[0] if len(df) > 0 else ''
        
        # 填充缺失字段
        for target_field in COLUMN_MAP_KR.values():
            if target_field not in transformed:
                transformed[target_field] = ''
        
        return transformed


class SKQualityChecker:
    """韩国SK数据质量检查器"""
    
    @staticmethod
    def check_row_quality(row_data: Dict) -> Dict:
        """检查单行数据质量"""
        issues = []
        quality_score = 100  # 初始分数
        
        # 1. 检查必填字段
        required_fields = ['工单号', 'SN', '型号']
        for field in required_fields:
            value = row_data.get(field, '')
            if not value or str(value).strip() == '':
                issues.append(f"必填字段缺失: {field}")
                quality_score -= 25
        
        # 2. 检查数据格式
        ticket_value = row_data.get('工单号', '')
        if ticket_value and not re.match(r'^[A-Z0-9]{6,}$', str(ticket_value)):
            issues.append(f"工单号格式异常: {ticket_value}")
            quality_score -= 10
        
        # 3. 检查故障和维修描述
        fault_desc = row_data.get('故障描述', '')
        repair_desc = row_data.get('维修详情', '')
        if not fault_desc and not repair_desc:
            issues.append("故障和维修描述均为空")
            quality_score -= 15
        
        return {
            'score': max(0, quality_score),
            'issues': issues,
            'has_issues': len(issues) > 0
        }
    
    @staticmethod
    def validate_batch(df: pd.DataFrame) -> pd.DataFrame:
        """批量验证数据"""
        df_validated = df.copy()
        quality_scores = []
        
        for idx, row in df.iterrows():
            # 将行转换为字典进行质量检查
            row_dict = row.to_dict()
            quality_result = SKQualityChecker.check_row_quality(row_dict)
            quality_scores.append(quality_result['score'])
            
            # 添加质量信息到行
            df_validated.at[idx, '_quality_score'] = quality_result['score']
            df_validated.at[idx, '_issues'] = ';'.join(quality_result['issues'])
            df_validated.at[idx, '_has_issues'] = quality_result['has_issues']
        
        return df_validated, quality_scores


def process_sk_with_intelligence(file_path: str, progress_cb=None, on_row_done=None, 
                                stop_flag_getter=None) -> pd.DataFrame:
    """
    智能处理韩国SK文件的主函数
    """
    print(f"智能处理韩国SK文件: {Path(file_path).name}")
    
    try:
        # 1. 分析文件
        analyzer = SKFileAnalyzer()
        analysis_result = analyzer.analyze_file(file_path)
        
        if 'error' in analysis_result:
            raise ValueError(f"文件分析失败: {analysis_result['error']}")
        
        # 2. 读取数据
        header_row = analysis_result['header_row']
        df = pd.read_excel(file_path, skiprows=header_row)
        print(f"读取到数据: {len(df)}行")
        
        # 3. 创建自定义映射
        transformer = SKDataTransformer(analyzer)
        custom_mapping = transformer.create_custom_mapping(df, analysis_result)
        print(f"创建映射: {len(custom_mapping)}个字段")
        
        # 4. 数据质量检查
        df_validated, quality_scores = SKQualityChecker.validate_batch(df)
        avg_quality = np.mean(quality_scores) if quality_scores else 0
        print(f"数据质量平均分: {avg_quality:.1f}")
        
        # 5. 使用custom_mapping转换数据
        processed_rows = []
        
        for idx, row in df_validated.iterrows():
            if stop_flag_getter and stop_flag_getter():
                break
            
            # 转换数据格式
            transformed = transformer.transform_dataframe(pd.DataFrame([row]), custom_mapping)
            
            # TODO: 这里可以调用原来的process_row_kr进行实际处理
            # 暂时先用转换后的数据
            processed_row = transformed.copy()
            
            # 添加固定字段
            processed_row['区域'] = FIXED_REGION_KR
            processed_row['代理'] = FIXED_AGENT_KR
            
            # 补充其他处理...
            
            processed_rows.append(processed_row)
            
            if on_row_done:
                on_row_done(processed_row)
            
            if progress_cb:
                progress_cb(idx + 1, len(df_validated))
        
        # 创建结果DataFrame
        result_df = pd.DataFrame(processed_rows)
        
        # 确保所有输出列都存在
        for col in OUTPUT_COLUMNS_KR:
            if col not in result_df.columns:
                result_df[col] = ''
        
        # 重新排列列顺序
        result_df = result_df[OUTPUT_COLUMNS_KR]
        
        print(f"处理完成: {len(result_df)}行")
        return result_df
        
    except Exception as e:
        print(f"处理失败: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def test_sk_processor():
    """测试韩国SK处理器"""
    from pathlib import Path
    
    test_file = Path(__file__).parent.parent / "原始工单" / "韩国SK原始表格.xlsx"
    
    if test_file.exists():
        print(f"测试文件: {test_file.name}")
        result = process_sk_with_intelligence(str(test_file))
        
        if len(result) > 0:
            print(f"处理成功: {len(result)}行")
            print("前3行结果:")
            print(result.head(3))
        else:
            print("处理失败或没有数据")
    else:
        print(f"测试文件不存在: {test_file}")


if __name__ == "__main__":
    test_sk_processor()