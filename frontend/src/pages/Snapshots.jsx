import React, { useState, useEffect } from 'react';
import { Table, Button, Modal, Upload, Input, Space, Popconfirm, Tag, Descriptions, message } from 'antd';
import { UploadOutlined, DeleteOutlined, EyeOutlined, CloudUploadOutlined, DatabaseOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { snapshotApi } from '../api';

export default function SnapshotsPage() {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploadModal, setUploadModal] = useState(false);
  const [detailModal, setDetailModal] = useState(false);
  const [detail, setDetail] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadName, setUploadName] = useState('');

  const load = async () => {
    setLoading(true);
    try { setList((await snapshotApi.list()).data); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const onUpload = async () => {
    if (!uploadFile || !uploadName) {
      message.warning('请输入名称并选择文件');
      return;
    }
    setUploading(true);
    try {
      await snapshotApi.upload(uploadFile, uploadName);
      message.success('快照上传成功');
      setUploadModal(false);
      setUploadFile(null);
      setUploadName('');
      load();
    } catch (e) {
      message.error(e.response?.data?.detail || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const viewDetail = async (id) => {
    try {
      const { data } = await snapshotApi.detail(id);
      setDetail(data);
      setDetailModal(true);
    } catch {
      message.error('获取详情失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    {
      title: '数据库信息', dataIndex: 'db_info', render: (v) => v ? (
        <Space size={4} direction="vertical" style={{ fontSize: 12 }}>
          <span>{v.banner?.split(' - ')[0] || v.version}</span>
          <span style={{ color: '#888' }}>{v.host}:{v.port}/{v.db_name}</span>
        </Space>
      ) : '-'
    },
    {
      title: 'Schema', dataIndex: 'schema_list', width: 80,
      render: (v) => <Tag color="blue">{v?.length || 0} 个</Tag>
    },
    {
      title: '统计', dataIndex: 'summary', width: 240,
      render: (v) => v ? (
        <Space size={[4, 4]} wrap>
          <Tag>表 {(v.total_tables || 0).toLocaleString()}</Tag>
          <Tag>对象 {(v.total_objects || 0).toLocaleString()}</Tag>
          <Tag>行 {(v.total_rows || 0).toLocaleString()}</Tag>
        </Space>
      ) : '-'
    },
    {
      title: '文件大小', dataIndex: 'file_size', width: 110,
      render: (v) => {
        if (!v) return '-';
        if (v >= 1073741824) return `${(v / 1073741824).toFixed(1)} GB`;
        if (v >= 1048576) return `${(v / 1048576).toFixed(1)} MB`;
        return `${(v / 1024).toFixed(0)} KB`;
      }
    },
    {
      title: '上传时间', dataIndex: 'created_at', width: 170,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm:ss')
    },
    {
      title: '操作', width: 150, render: (_, r) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => viewDetail(r.id)}>查看</Button>
          <Popconfirm title="确定删除？关联的比对任务也将被删除。" onConfirm={async () => { try { await snapshotApi.remove(r.id); message.success('已删除'); load(); } catch (e) { message.error(e.response?.data?.detail || '删除失败'); } }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>源库快照</h2>
        <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setUploadModal(true)}>上传快照</Button>
      </div>

      <Table dataSource={list} columns={columns} rowKey="id" loading={loading} size="middle" />

      <Modal title="上传源库快照" open={uploadModal} onOk={onUpload} onCancel={() => setUploadModal(false)}
        confirmLoading={uploading} okText="上传">
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>快照名称</div>
          <Input placeholder="如: 源库-生产环境-20260306" value={uploadName} onChange={(e) => setUploadName(e.target.value)} />
        </div>
        <div>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>选择快照文件 (.json)</div>
          <Upload
            accept=".json"
            maxCount={1}
            beforeUpload={(file) => { setUploadFile(file); return false; }}
            onRemove={() => setUploadFile(null)}
          >
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
          <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>
            使用 export_tool.py 从源库导出的 JSON 快照文件
          </div>
        </div>
      </Modal>

      <Modal title="快照详情" open={detailModal} onCancel={() => setDetailModal(false)} footer={null} width={700}>
        {detail && (
          <div>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="数据库">{detail.db_info?.db_name}</Descriptions.Item>
              <Descriptions.Item label="版本">{detail.db_info?.version}</Descriptions.Item>
              <Descriptions.Item label="主机" span={2}>{detail.db_info?.host}:{detail.db_info?.port}</Descriptions.Item>
              <Descriptions.Item label="Banner" span={2}>{detail.db_info?.banner}</Descriptions.Item>
              <Descriptions.Item label="Schema 数">{detail.summary?.schema_count}</Descriptions.Item>
              <Descriptions.Item label="总表数">{detail.summary?.total_tables}</Descriptions.Item>
              <Descriptions.Item label="总对象数">{detail.summary?.total_objects}</Descriptions.Item>
              <Descriptions.Item label="总行数">{detail.summary?.total_rows?.toLocaleString()}</Descriptions.Item>
            </Descriptions>
            <h4>各 Schema 概况</h4>
            <Table
              dataSource={Object.entries(detail.schemas || {}).map(([name, stats]) => ({ key: name, name, ...stats }))}
              size="small" pagination={false}
              columns={[
                { title: 'Schema', dataIndex: 'name' },
                { title: '表数', dataIndex: 'table_count', width: 80 },
                { title: '对象数', dataIndex: 'object_count', width: 80 },
                { title: '总行数', dataIndex: 'total_rows', width: 120, render: (v) => (v || 0).toLocaleString() },
              ]}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}
