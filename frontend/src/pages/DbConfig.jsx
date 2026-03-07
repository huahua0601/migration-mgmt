import React, { useState, useEffect } from 'react';
import { Table, Button, Modal, Form, Input, Select, InputNumber, Space, Popconfirm, Tag, Result, Alert, message } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, ApiOutlined, ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { dbApi } from '../api';

export default function DbConfigPage() {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [testing, setTesting] = useState({});
  const [modalTesting, setModalTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try { setList((await dbApi.list()).data); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditing(null);
    setTestResult(null);
    form.resetFields();
    form.setFieldsValue({ db_type: 'oracle', port: 1521 });
    setModal(true);
  };
  const openEdit = (r) => {
    setEditing(r);
    setTestResult(null);
    form.setFieldsValue(r);
    setModal(true);
  };

  const onSave = async () => {
    const values = await form.validateFields();
    if (editing) {
      await dbApi.update(editing.id, values);
      message.success('更新成功');
    } else {
      await dbApi.create(values);
      message.success('创建成功');
    }
    setModal(false);
    load();
  };

  const onTestInList = async (id) => {
    setTesting((p) => ({ ...p, [id]: true }));
    try {
      const { data } = await dbApi.test(id);
      if (data.status === 'ok') message.success(`连接成功 (${data.version})`);
      else message.error(`连接失败: ${data.detail}`);
    } catch {
      message.error('测试失败');
    } finally {
      setTesting((p) => ({ ...p, [id]: false }));
    }
  };

  const onTestInModal = async () => {
    try {
      await form.validateFields(['db_type', 'host', 'port', 'username', 'password']);
    } catch {
      message.warning('请先填写完数据库连接信息');
      return;
    }
    const values = form.getFieldsValue();
    setModalTesting(true);
    setTestResult(null);
    try {
      const { data } = await dbApi.testDirect({
        db_type: values.db_type,
        host: values.host,
        port: values.port,
        service_name: values.service_name,
        username: values.username,
        password: values.password,
      });
      setTestResult(data);
    } catch (e) {
      setTestResult({ status: 'error', detail: e.response?.data?.detail || '请求失败' });
    } finally {
      setModalTesting(false);
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '类型', dataIndex: 'db_type', width: 80, render: (v) => <Tag>{v.toUpperCase()}</Tag> },
    { title: '主机', dataIndex: 'host', ellipsis: true },
    { title: '端口', dataIndex: 'port', width: 80 },
    { title: '服务名', dataIndex: 'service_name', width: 100 },
    { title: '用户名', dataIndex: 'username', width: 100 },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '操作', width: 200, render: (_, r) => (
        <Space>
          <Button size="small" icon={<ApiOutlined />} loading={testing[r.id]} onClick={() => onTestInList(r.id)}>测试</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title="确定删除?" onConfirm={async () => { await dbApi.remove(r.id); message.success('已删除'); load(); }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>数据库配置</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增数据库</Button>
      </div>
      <Table dataSource={list} columns={columns} rowKey="id" loading={loading} size="middle" />
      <Modal
        title={editing ? '编辑数据库' : '新增数据库'}
        open={modal}
        width={560}
        onOk={onSave}
        onCancel={() => setModal(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如: 源库-Oracle" />
          </Form.Item>
          <Space style={{ width: '100%' }} size={16}>
            <Form.Item name="db_type" label="数据库类型" rules={[{ required: true }]}>
              <Select style={{ width: 140 }} options={[
                { value: 'oracle', label: 'Oracle' },
                { value: 'mysql', label: 'MySQL' },
                { value: 'postgresql', label: 'PostgreSQL' },
              ]} />
            </Form.Item>
            <Form.Item name="port" label="端口" rules={[{ required: true }]}>
              <InputNumber style={{ width: 120 }} />
            </Form.Item>
          </Space>
          <Form.Item name="host" label="主机地址" rules={[{ required: true }]}>
            <Input placeholder="hostname or IP" />
          </Form.Item>
          <Form.Item name="service_name" label="服务名 / SID">
            <Input placeholder="如: ORCL" />
          </Form.Item>
          <Space style={{ width: '100%' }} size={16}>
            <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true }]}>
              <Input.Password />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>

        <div style={{
          borderTop: '1px solid #f0f0f0', paddingTop: 16, marginTop: 8,
        }}>
          <Button
            icon={<ThunderboltOutlined />}
            loading={modalTesting}
            onClick={onTestInModal}
            style={{ marginBottom: testResult ? 12 : 0 }}
          >
            测试连接
          </Button>

          {testResult && testResult.status === 'ok' && (
            <Alert
              type="success"
              showIcon
              icon={<CheckCircleOutlined />}
              message="连接成功"
              description={
                <div style={{ fontSize: 13 }}>
                  <div><b>版本:</b> {testResult.version}</div>
                  <div><b>Banner:</b> {testResult.banner}</div>
                  <div><b>数据库名:</b> {testResult.db_name}</div>
                  <div><b>用户数:</b> {testResult.user_count}</div>
                </div>
              }
            />
          )}

          {testResult && testResult.status === 'error' && (
            <Alert
              type="error"
              showIcon
              icon={<CloseCircleOutlined />}
              message="连接失败"
              description={testResult.detail}
            />
          )}
        </div>
      </Modal>
    </div>
  );
}
