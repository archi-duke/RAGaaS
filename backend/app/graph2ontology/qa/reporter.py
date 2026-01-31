"""QA 리포트 생성"""

from pathlib import Path
from datetime import datetime
from typing import Union, Optional,  Optional, Union
from dataclasses import dataclass, field


@dataclass
class QAMetrics:
    """QA 지표"""
    # 문서/청크
    total_documents: int = 0
    total_oe_chunks: int = 0
    total_rag_chunks: int = 0
    avg_oe_chunk_length: float = 0.0
    avg_rag_chunk_length: float = 0.0
    
    # 추출
    total_candidates_raw: int = 0
    total_candidates_filtered: int = 0
    filtering_ratio: float = 0.0
    
    # 온톨로지
    total_classes: int = 0
    total_properties: int = 0
    total_relations: int = 0
    total_instances: int = 0
    total_triples: int = 0
    
    # 엔티티 레지스트리
    total_entities: int = 0
    total_aliases: int = 0
    
    # 실행 정보
    run_id: str = ""
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0.0
    
    # 에러
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class QAReporter:
    """QA 리포트 생성기"""
    
    def __init__(self, run_id: str):
        """
        Args:
            run_id: 실행 ID
        """
        self.metrics = QAMetrics(run_id=run_id)
        self.metrics.start_time = datetime.now().isoformat()
    
    def add_document_stats(
        self,
        doc_id: str,
        oe_chunks: int,
        rag_chunks: int,
        oe_avg_len: float,
        rag_avg_len: float,
    ) -> None:
        """문서 통계 추가"""
        self.metrics.total_documents += 1
        self.metrics.total_oe_chunks += oe_chunks
        self.metrics.total_rag_chunks += rag_chunks
        
        # 평균 길이 업데이트 (running average)
        n = self.metrics.total_documents
        self.metrics.avg_oe_chunk_length = (
            (self.metrics.avg_oe_chunk_length * (n - 1) + oe_avg_len) / n
        )
        self.metrics.avg_rag_chunk_length = (
            (self.metrics.avg_rag_chunk_length * (n - 1) + rag_avg_len) / n
        )
    
    def add_extraction_stats(
        self,
        raw_count: int,
        filtered_count: int,
        classes: int = 0,
        properties: int = 0,
        relations: int = 0,
        instances: int = 0,
        triples: int = 0,
    ) -> None:
        """추출 통계 추가"""
        self.metrics.total_candidates_raw += raw_count
        self.metrics.total_candidates_filtered += filtered_count
        self.metrics.total_classes += classes
        self.metrics.total_properties += properties
        self.metrics.total_relations += relations
        self.metrics.total_instances += instances
        self.metrics.total_triples += triples
        
        # 필터링 비율 계산
        if self.metrics.total_candidates_raw > 0:
            self.metrics.filtering_ratio = (
                1.0 - self.metrics.total_candidates_filtered / self.metrics.total_candidates_raw
            )
    
    def add_entity_stats(self, entities: int, aliases: int = 0) -> None:
        """엔티티 통계 추가"""
        self.metrics.total_entities = entities
        self.metrics.total_aliases = aliases
    
    def add_error(self, error: str) -> None:
        """에러 추가"""
        self.metrics.errors.append(f"[{datetime.now().isoformat()}] {error}")
    
    def add_warning(self, warning: str) -> None:
        """경고 추가"""
        self.metrics.warnings.append(f"[{datetime.now().isoformat()}] {warning}")
    
    def finalize(self) -> None:
        """리포트 종료"""
        self.metrics.end_time = datetime.now().isoformat()
        
        # duration 계산
        start = datetime.fromisoformat(self.metrics.start_time)
        end = datetime.fromisoformat(self.metrics.end_time)
        self.metrics.duration_seconds = (end - start).total_seconds()
    
    def generate_markdown(self) -> str:
        """마크다운 리포트 생성"""
        m = self.metrics
        
        report = f"""# QA Report

## 실행 정보

| 항목 | 값 |
|------|-----|
| Run ID | `{m.run_id}` |
| 시작 시간 | {m.start_time} |
| 종료 시간 | {m.end_time} |
| 소요 시간 | {m.duration_seconds:.2f}초 |

## 문서/청크 통계

| 항목 | 값 |
|------|-----|
| 총 문서 수 | {m.total_documents} |
| OE-Chunk 수 | {m.total_oe_chunks} |
| RAG-Chunk 수 | {m.total_rag_chunks} |
| OE-Chunk 평균 길이 | {m.avg_oe_chunk_length:.0f} 문자 |
| RAG-Chunk 평균 길이 | {m.avg_rag_chunk_length:.0f} 문자 |

## 추출 통계

| 항목 | 값 |
|------|-----|
| 원본 후보 수 | {m.total_candidates_raw} |
| 필터링 후 후보 수 | {m.total_candidates_filtered} |
| 필터링 비율 | {m.filtering_ratio:.1%} |

## 온톨로지 통계

| 항목 | 값 |
|------|-----|
| 클래스 | {m.total_classes} |
| 데이터 속성 | {m.total_properties} |
| 객체 속성(관계) | {m.total_relations} |
| 인스턴스 | {m.total_instances} |
| 트리플 | {m.total_triples} |

## 엔티티 레지스트리

| 항목 | 값 |
|------|-----|
| 총 엔티티 | {m.total_entities} |
| 별칭 수 | {m.total_aliases} |

"""
        
        if m.errors:
            report += "## 에러\n\n"
            for err in m.errors:
                report += f"- {err}\n"
            report += "\n"
        
        if m.warnings:
            report += "## 경고\n\n"
            for warn in m.warnings:
                report += f"- {warn}\n"
            report += "\n"
        
        return report
    
    def save(self, output_path: Union[str, Path]) -> None:
        """리포트 저장"""
        self.finalize()
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.generate_markdown())
