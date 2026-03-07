import React, { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Table, Tag, Tabs, Select, Space, Statistic, Row, Col, Progress, Button, Descriptions, Collapse } from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  ArrowLeftOutlined, SyncOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { compApi } from '../api';

const statusColor = { match: 'green', mismatch: 'red', source_only: 'orange', target_only: 'purple' };
const statusIcon = {
  match: <CheckCircleOutlined />, mismatch: <CloseCircleOutlined />,
  source_only: <ExclamationCircleOutlined />, target_only: <ExclamationCircleOutlined />,
};
const statusLabel = { match: '一致', mismatch: '不一致', source_only: '仅源库', target_only: '仅目标库' };

const OBJ_TYPES = ['TABLE', 'DATA_COUNT', 'DATA_CHECKSUM', 'INDEX', 'VIEW', 'SEQUENCE',
  'FUNCTION', 'PROCEDURE', 'PACKAGE', 'TRIGGER', 'TYPE', 'SYNONYM', 'MVIEW', 'DB_LINK'];

export default function ComparisonDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState(null);
  const [summary, setSummary] = useState(null);
  const [results, setResults] = useState([]);
  const [filters, setFilters] = useState({ schema: null, type: null, status: null });

  const load = async () => {
    const [t, s] = await Promise.all([compApi.get(id), compApi.summary(id)]);
    setTask(t.data);
    setSummary(s.data);
  };

  const loadResults = async () => {
    const params = {};
    if (filters.schema) params.schema_name = filters.schema;
    if (filters.type) params.object_type = filters.type;
    if (filters.status) params.match_status = filters.status;
    const { data } = await compApi.results(id, params);
    setResults(data);
  };

  useEffect(() => { load(); }, [id]);
  useEffect(() => { loadResults(); }, [id, filters]);
  useEffect(() => {
    if (task?.status === 'running') { const iv = setInterval(load, 5000); return () => clearInterval(iv); }
  }, [task?.status]);

  const schemas = useMemo(() => summary?.by_schema ? Object.keys(summary.by_schema).sort() : [], [summary]);

  const resultColumns = [
    { title: 'Schema', dataIndex: 'schema_name', width: 150 },
    { title: '对象类型', dataIndex: 'object_type', width: 130, render: (v) => <Tag>{v}</Tag> },
    { title: '对象名称', dataIndex: 'object_name', ellipsis: true },
    {
      title: '比对结果', dataIndex: 'match_status', width: 110,
      render: (v) => <Tag color={statusColor[v]} icon={statusIcon[v]}>{statusLabel[v]}</Tag>,
    },
    { title: '源库值', dataIndex: 'source_value', ellipsis: true, width: 180 },
    { title: '目标库值', dataIndex: 'target_value', ellipsis: true, width: 180 },
  ];

  if (!task) return null;
  const total = summary?.total || {};

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/comparisons')}>返回</Button>
        <h2 style={{ margin: 0 }}>{task.name}</h2>
        <Tag color={task.status === 'completed' ? 'green' : task.status === 'running' ? 'blue' : 'default'}
          icon={task.status === 'running' ? <SyncOutlined spin /> : null}>
          {task.status}
        </Tag>
      </Space>

      {task.status === 'running' && <Progress percent={task.progress} style={{ marginBottom: 16 }} />}

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="总比对项" value={total.match + total.mismatch + total.source_only + total.target_only || 0} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="一致" value={total.match || 0} valueStyle={{ color: '#52c41a' }} prefix={<CheckCircleOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="不一致" value={total.mismatch || 0} valueStyle={{ color: '#ff4d4f' }} prefix={<CloseCircleOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="仅一端存在" value={(total.source_only || 0) + (total.target_only || 0)} valueStyle={{ color: '#faad14' }} prefix={<ExclamationCircleOutlined />} /></Card>
        </Col>
      </Row>

      {schemas.length > 0 && (
        <Card title="各 Schema 概览" size="small" style={{ marginBottom: 24 }}>
          <Table dataSource={schemas.map((s) => ({ key: s, schema: s, ...summary.by_schema[s] }))}
            size="small" pagination={false} columns={[
              { title: 'Schema', dataIndex: 'schema', width: 180 },
              { title: '一致', dataIndex: 'match', width: 80, render: (v) => <Tag color="green">{v || 0}</Tag> },
              { title: '不一致', dataIndex: 'mismatch', width: 80, render: (v) => <Tag color={v ? 'red' : 'default'}>{v || 0}</Tag> },
              { title: '仅源库', dataIndex: 'source_only', width: 80, render: (v) => <Tag color={v ? 'orange' : 'default'}>{v || 0}</Tag> },
              { title: '仅目标库', dataIndex: 'target_only', width: 80, render: (v) => <Tag color={v ? 'purple' : 'default'}>{v || 0}</Tag> },
              {
                title: '一致率', width: 120, render: (_, r) => {
                  const t = (r.match || 0) + (r.mismatch || 0) + (r.source_only || 0) + (r.target_only || 0);
                  const pct = t > 0 ? Math.round((r.match || 0) / t * 100) : 0;
                  return <Progress percent={pct} size="small" status={pct === 100 ? 'success' : 'exception'} />;
                }
              },
            ]} />
        </Card>
      )}

      <Card title="比对明细" size="small">
        <Space style={{ marginBottom: 16 }}>
          <Select allowClear placeholder="Schema" style={{ width: 180 }} value={filters.schema}
            onChange={(v) => setFilters((p) => ({ ...p, schema: v }))}
            options={schemas.map((s) => ({ value: s, label: s }))} />
          <Select allowClear placeholder="对象类型" style={{ width: 160 }} value={filters.type}
            onChange={(v) => setFilters((p) => ({ ...p, type: v }))}
            options={OBJ_TYPES.map((t) => ({ value: t, label: t }))} />
          <Select allowClear placeholder="比对状态" style={{ width: 140 }} value={filters.status}
            onChange={(v) => setFilters((p) => ({ ...p, status: v }))}
            options={Object.entries(statusLabel).map(([k, v]) => ({ value: k, label: v }))} />
          <Button onClick={() => setFilters({ schema: null, type: null, status: null })}>重置</Button>
        </Space>
        <Table dataSource={results} columns={resultColumns} rowKey="id" size="small"
          pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          expandable={{
            expandedRowRender: (r) => (
              <div style={{ padding: 8 }}>
                {r.source_value && <div><b>源库:</b> <pre style={{ maxHeight: 200, overflow: 'auto', background: '#f5f5f5', padding: 8, borderRadius: 4 }}>{r.source_value}</pre></div>}
                {r.target_value && <div><b>目标库:</b> <pre style={{ maxHeight: 200, overflow: 'auto', background: '#f5f5f5', padding: 8, borderRadius: 4 }}>{r.target_value}</pre></div>}
                {r.details && <div><b>详情:</b> <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4 }}>{JSON.stringify(r.details, null, 2)}</pre></div>}
              </div>
            ),
          }} />
      </Card>
    </div>
  );
}
