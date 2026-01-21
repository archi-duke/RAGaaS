import React, { useEffect, useState } from 'react';
import { kbApi } from '../services/api';
import { Grid, GridColumn, type GridPageChangeEvent, type GridSortChangeEvent, type GridFilterChangeEvent } from '@progress/kendo-react-grid';
import type { SortDescriptor, CompositeFilterDescriptor } from '@progress/kendo-data-query';
import '@progress/kendo-theme-bootstrap/dist/all.css';
import ChunkDetailModal from './ChunkDetailModal';

interface Triple {
    subject: string;
    predicate: string;
    object: string;
    doc_id?: string;
    doc_filename?: string;
    chunk_id?: string;
    chunk_text?: string;
    confidence?: number;
}

interface GraphDataTableProps {
    kbId: string;
    backend: string;
}

export default function GraphDataTable({ kbId, backend }: GraphDataTableProps) {
    const [triples, setTriples] = useState<Triple[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [take, setTake] = useState(20); // Default page size
    const [isLoading, setIsLoading] = useState(true);
    const [hasChunkMappings, setHasChunkMappings] = useState(true);
    const [selectedChunk, setSelectedChunk] = useState<{ id: string; content: string } | null>(null);

    // Sort and Filter states
    const [sort, setSort] = useState<SortDescriptor[]>([]);
    const [filter, setFilter] = useState<CompositeFilterDescriptor>({ logic: 'and', filters: [] });

    useEffect(() => {
        // Reset paging and filters when context changes
        setSkip(0);
        setSort([]);
        setFilter({ logic: 'and', filters: [] });
        loadTriples(0, take, [], { logic: 'and', filters: [] });
    }, [kbId, backend]);

    const loadTriples = async (skipVal: number, takeVal: number, sortVal: SortDescriptor[], filterVal: CompositeFilterDescriptor) => {
        setIsLoading(true);
        try {
            // Pass sort and filter to API
            const response = await kbApi.getTriples(kbId, backend, skipVal, takeVal, sortVal, filterVal);
            setTriples(response.data.triples || []);
            setTotal(response.data.total || 0);
            setHasChunkMappings(response.data.has_chunk_mappings ?? true);
        } catch (error) {
            console.error('Failed to load triples:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const pageChange = (event: GridPageChangeEvent) => {
        setSkip(event.page.skip);
        setTake(event.page.take);
        loadTriples(event.page.skip, event.page.take, sort, filter);
    };

    const handleSortChange = (event: GridSortChangeEvent) => {
        setSort(event.sort);
        setSkip(0); // Reset to first page on sort
        loadTriples(0, take, event.sort, filter);
    };

    const handleFilterChange = (event: GridFilterChangeEvent) => {
        setFilter(event.filter);
        setSkip(0); // Reset to first page on filter
        loadTriples(0, take, sort, event.filter);
    };

    const handleChunkClick = async (chunkId: string) => {
        try {
            const response = await kbApi.getChunk(kbId, chunkId);
            setSelectedChunk({
                id: chunkId,
                content: response.data.content
            });
        } catch (error) {
            console.error('Failed to load chunk:', error);
            alert('Failed to load chunk content');
        }
    };

    // Shared styles
    const centerStyle = { textAlign: 'center', fontSize: '0.85rem' } as React.CSSProperties;

    const ChunkCell = (props: any) => {
        const chunkId = props.dataItem.chunk_id;
        const style = { ...props.style, ...centerStyle };

        return (
            <td
                style={style}
                className={props.className}
                colSpan={props.colSpan || 1}
                role="gridcell"
                aria-colindex={props.ariaColumnIndex}
            >
                {chunkId ? (
                    <span
                        onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleChunkClick(chunkId);
                        }}
                        onMouseDown={(e) => e.stopPropagation()}
                        style={{
                            color: '#3b82f6',
                            textDecoration: 'underline',
                            cursor: 'pointer',
                            fontWeight: 500,
                            padding: '2px 4px'
                        }}
                        title={`Source Chunk ID: ${chunkId}\n(Note: Multiple triples may originate from the same text chunk)`}
                    >
                        {chunkId.substring(0, 8)}...
                    </span>
                ) : (
                    <span style={{ color: '#94a3b8' }}>-</span>
                )}
            </td>
        );
    };

    const PredicateCell = (props: any) => {
        const style = { ...props.style, ...centerStyle, fontStyle: 'italic', color: '#0284c7' };
        return (
            <td
                style={style}
                className={props.className}
                colSpan={props.colSpan || 1}
                role="gridcell"
            >
                {props.dataItem.predicate}
            </td>
        );
    };

    const DocumentCell = (props: any) => {
        const { doc_filename, doc_id } = props.dataItem;
        const style = { ...props.style, ...centerStyle, fontSize: '0.85em' };

        // If filename is missing, show shortened ID with distinct style
        const isUnknown = !doc_filename;
        const display = doc_filename || (doc_id ? `${doc_id.substring(0, 8)}...` : '-');

        return (
            <td
                style={{ ...style, color: isUnknown ? '#94a3b8' : '#64748b' }}
                className={props.className}
                colSpan={props.colSpan || 1}
                role="gridcell"
                title={isUnknown ? `Document ID: ${doc_id} (Metadata missing or deleted)` : doc_filename}
            >
                {display}
                {isUnknown && doc_id && <span style={{ fontSize: '0.7em', marginLeft: '4px', fontStyle: 'italic' }}>(del)</span>}
            </td>
        );
    };

    return (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column', padding: '20px' }}>
            {/* Global styles for Grid Header */}
            <style>{`
                .k-grid th, .k-grid td {
                    text-align: center !important;
                    vertical-align: middle !important;
                    font-size: 0.8rem !important;
                }
                .k-grid-header .k-header {
                    text-align: center !important;
                    justify-content: center !important;
                    font-weight: bold;
                    color: #334155;
                    font-size: 0.8rem !important;
                }
                .k-grid-header .k-header .k-link {
                    justify-content: center;
                }
                .k-pager {
                    font-size: 0.75rem !important;
                }
                .k-pager .k-link, .k-pager .k-pager-info, .k-pager .k-button {
                    font-size: 0.75rem !important;
                }
                .k-pager .k-button {
                    padding: 2px 8px !important;
                }
            `}</style>

            {/* Missing Mapping Warning */}
            {!hasChunkMappings && (
                <div style={{
                    padding: '0.75rem 1rem',
                    marginBottom: '1rem',
                    backgroundColor: '#fef3c7',
                    border: '1px solid #f59e0b',
                    borderRadius: '6px',
                    color: '#92400e',
                    fontSize: '0.85rem'
                }}>
                    ⚠️ No chunk mapping info found. Please re-index the document to enable chunk preview.
                </div>
            )}

            <div style={{ flex: 1, overflow: 'hidden', opacity: isLoading ? 0.6 : 1, position: 'relative' }}>
                {isLoading && (
                    <div style={{
                        position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2
                    }}>
                        Loading...
                    </div>
                )}
                <Grid
                    style={{ height: '100%' }}
                    data={triples}
                    skip={skip}
                    take={take}
                    total={total}
                    pageable={{
                        buttonCount: 5,
                        info: true,
                        type: 'numeric',
                        pageSizes: [10, 20, 50, 100],
                        previousNext: true
                    }}
                    onPageChange={pageChange}
                    resizable={true}
                    sortable={true}
                    sort={sort}
                    onSortChange={handleSortChange}
                    filterable={true}
                    filter={filter}
                    onFilterChange={handleFilterChange}
                >
                    <GridColumn field="subject" title="Subject" filterable={true} />
                    <GridColumn field="predicate" title="Predicate" cell={PredicateCell} filterable={true} />
                    <GridColumn field="object" title="Object" filterable={true} />
                    <GridColumn field="confidence" title="Confidence" width="100px" filterable={false} />
                    <GridColumn field="doc_filename" title="Document" width="200px" cell={DocumentCell} filterable={false} />
                    <GridColumn field="chunk_id" title="Chunk" width="140px" cell={ChunkCell} filterable={false} />
                </Grid>
            </div>

            {/* Chunk Preview Modal with Unified Component */}
            <ChunkDetailModal
                isOpen={!!selectedChunk}
                onClose={() => setSelectedChunk(null)}
                chunk={selectedChunk}
                isGraphEnabled={true}
                kbId={kbId}
            />
        </div>
    );
}
