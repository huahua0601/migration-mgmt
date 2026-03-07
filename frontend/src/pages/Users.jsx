import React, { useState, useEffect } from 'react';
import { Table, Button, Modal, Form, Input, Select, Space, Popconfirm, Tag, message } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { userApi } from '../api';

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try { setUsers((await userApi.list()).data); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const openCreate = () => { setEditing(null); form.resetFields(); setModal(true); };
  const openEdit = (r) => { setEditing(r); form.setFieldsValue(r); setModal(true); };

  const onSave = async () => {
    const values = await form.validateFields();
    if (editing) {
      await userApi.update(editing.id, values);
      message.success('更新成功');
    } else {
      await userApi.create(values);
      message.success('创建成功');
    }
    setModal(false);
    load();
  };

  const onDelete = async (id) => {
    await userApi.remove(id);
    message.success('已删除');
    load();
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username' },
    { title: '邮箱', dataIndex: 'email' },
    { title: '角色', dataIndex: 'role', render: (v) => <Tag color={v === 'admin' ? 'blue' : 'default'}>{v}</Tag> },
    { title: '状态', dataIndex: 'is_active', render: (v) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '禁用'}</Tag> },
    {
      title: '操作', width: 150, render: (_, r) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title="确定删除?" onConfirm={() => onDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>用户管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
      </div>
      <Table dataSource={users} columns={columns} rowKey="id" loading={loading} size="middle" />
      <Modal title={editing ? '编辑用户' : '新建用户'} open={modal}
        onOk={onSave} onCancel={() => setModal(false)} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input disabled={!!editing} />
          </Form.Item>
          {!editing && (
            <Form.Item name="password" label="密码" rules={[{ required: true }]}>
              <Input.Password />
            </Form.Item>
          )}
          <Form.Item name="email" label="邮箱"><Input /></Form.Item>
          <Form.Item name="role" label="角色" initialValue="user">
            <Select options={[{ value: 'admin', label: '管理员' }, { value: 'user', label: '普通用户' }]} />
          </Form.Item>
          {editing && (
            <Form.Item name="is_active" label="状态">
              <Select options={[{ value: 1, label: '启用' }, { value: 0, label: '禁用' }]} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
