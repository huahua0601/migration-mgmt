import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Button, Modal, Form, Input, Select, Space, Popconfirm, Tag, Progress, Radio, message } from 'antd';
import { PlusOutlined, DeleteOutlined, EyeOutlined, SyncOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { dbApi, compApi, snapshotApi } from '../api';

const statusColors = { pending: 'default', running: 'processing', completed: 'success', failed: 'error' };
const statusLabels = { pending: '待执行', running: '执行中', completed: '已完成', failed: '失败' };
const modeLabels = { snapshot_vs_db: '快照 vs 在线库', db_vs_db: '在线库 vs 在线库' };

export default function ComparisonListPage() {
  const [tasks, setTasks] = useState([]);
  const [dbList, setDbList] = useState([]);
  const [snapList, setSnapList] = useState([]);
  const [schemaList, setSchemaList] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    try {
      const [t, d, s] = await Promise.all([compApi.list(), dbApi.list(), snapshotApi.list()]);
      setTasks(t.data);
      setDbList(d.data);
      setSnapList(s.data);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); const iv = setInterval(load, 8000); return () => clearInterval(iv); }, []);

  const mode = Form.useWatch('mode', form) || 'snapshot_vs_db';

  const onSourceChange = async (type, id) => {
    try {
      const { data } = type === 'snapshot'
        ? await snapshotApi.schemas(id)
        : await dbApi.schemas(id);
      setSchemaList(data.schemas || []);
    } catch { setSchemaList([]); }
  };

  const onCreate = async () => {
    const values = await form.validateFields();
    await compApi.create(values);
    message.success('比对任务已创建');
    setModal(false);
    load();
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '任务名称', dataIndex: 'name', ellipsis: true },
    { title: '模式', dataIndex: 'mode', width: 140, render: (v) => <Tag color="blue">{modeLabels[v] || v}</Tag> },
    {
      title: '源 (快照/库)', width: 160,
      render: (_, r) => r.source_snapshot ? r.source_snapshot.name : (r.source_db?.name || '-')
    },
    { title: '目标库', render: (_, r) => r.target_db?.name || r.target_db_id },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v) => <Tag color={statusColors[v]} icon={v === 'running' ? <SyncOutlined spin /> : null}>{statusLabels[v]}</Tag>
    },
    { title: '进度', dataIndex: 'progress', width: 120, render: (v) => <Progress percent={v} size="small" /> },
    {
      title: '结果', dataIndex: 'summary', width: 280,
      render: (s) => s && !s.error ? (
        <Space size={[4, 4]} wrap>
          <Tag color="green">一致 {(s.match || 0).toLocaleString()}</Tag>
          <Tag color="red">不一致 {(s.mismatch || 0).toLocaleString()}</Tag>
          {(s.source_only > 0) && <Tag color="orange">仅源 {s.source_only}</Tag>}
          {(s.target_only > 0) && <Tag color="volcano">仅目标 {s.target_only}</Tag>}
        </Space>
      ) : s?.error ? <Tag color="red">错误</Tag> : '-'
    },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
    {
      title: '操作', width: 140, render: (_, r) => (
        <Space>
          <Button size="small" type="primary" icon={<EyeOutlined />} onClick={() => navigate(`/comparisons/${r.id}`)}>详情</Button>
          <Popconfirm title="确定删除?" onConfirm={async () => { await compApi.remove(r.id); load(); }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>数据比对</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); form.setFieldsValue({ mode: 'snapshot_vs_db' }); setSchemaList([]); setModal(true); }}>新建比对</Button>
      </div>
      <Table dataSource={tasks} columns={columns} rowKey="id" loading={loading} size="middle" scroll={{ x: 1300 }} />

      <Modal title="新建比对任务" open={modal} onOk={onCreate} onCancel={() => setModal(false)} width={560} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ mode: 'snapshot_vs_db' }}>
          <Form.Item name="name" label="任务名称" rules={[{ required: true }]}>
            <Input placeholder="如: 迁移验证-20260306" />
          </Form.Item>

          <Form.Item name="mode" label="比对模式">
            <Radio.Group>
              <Radio.Button value="snapshot_vs_db">快照 vs 在线库</Radio.Button>
              <Radio.Button value="db_vs_db">在线库 vs 在线库</Radio.Button>
            </Radio.Group>
          </Form.Item>

          {mode === 'snapshot_vs_db' && (
            <Form.Item name="source_snapshot_id" label="源库快照" rules={[{ required: true }]}>
              <Select placeholder="选择快照" onChange={(id) => onSourceChange('snapshot', id)}
                options={snapList.map((s) => ({
                  value: s.id,
                  label: `${s.name} (${s.db_info?.db_name || ''} - ${s.schema_list?.length || 0} schemas)`,
                }))} />
            </Form.Item>
          )}

          {mode === 'db_vs_db' && (
            <Form.Item name="source_db_id" label="源数据库" rules={[{ required: true }]}>
              <Select placeholder="选择源库" onChange={(id) => onSourceChange('db', id)}
                options={dbList.map((d) => ({ value: d.id, label: `${d.name} (${d.host})` }))} />
            </Form.Item>
          )}

          <Form.Item name="target_db_id" label="目标数据库" rules={[{ required: true }]}>
            <Select placeholder="选择目标库"
              options={dbList.map((d) => ({ value: d.id, label: `${d.name} (${d.host})` }))} />
          </Form.Item>

          <Form.Item name="schemas" label="选择 Schema（留空比对所有）">
            <Select mode="multiple" placeholder="选择 schema"
              options={schemaList.map((s) => ({ value: s, label: s }))} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
