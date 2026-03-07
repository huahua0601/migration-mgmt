import React, { useState, useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { ConfigProvider, Layout, Menu, Button, theme, Avatar, Dropdown, App as AntApp } from 'antd';
import {
  UserOutlined, DatabaseOutlined, SwapOutlined, LogoutOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined, CameraOutlined,
} from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import { authApi } from './api';
import LoginPage from './pages/Login';
import UsersPage from './pages/Users';
import DbConfigPage from './pages/DbConfig';
import SnapshotsPage from './pages/Snapshots';
import ComparisonListPage from './pages/ComparisonList';
import ComparisonDetailPage from './pages/ComparisonDetail';

const { Header, Sider, Content } = Layout;

function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [user, setUser] = useState(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    authApi.me().then((r) => setUser(r.data)).catch(() => navigate('/login'));
  }, []);

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const menuItems = [
    { key: '/db-configs', icon: <DatabaseOutlined />, label: '数据库配置' },
    { key: '/snapshots', icon: <CameraOutlined />, label: '源库快照' },
    { key: '/comparisons', icon: <SwapOutlined />, label: '数据比对' },
  ];
  if (user?.role === 'admin') {
    menuItems.unshift({ key: '/users', icon: <UserOutlined />, label: '用户管理' });
  }

  const userMenu = {
    items: [
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: logout },
    ],
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider trigger={null} collapsible collapsed={collapsed} theme="light"
        style={{ borderRight: '1px solid #f0f0f0' }}>
        <div style={{ height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: collapsed ? 16 : 18, color: '#1677ff', whiteSpace: 'nowrap', overflow: 'hidden' }}>
          {collapsed ? 'MM' : 'Migration Mgmt'}
        </div>
        <Menu mode="inline" selectedKeys={[location.pathname]}
          onClick={({ key }) => navigate(key)} items={menuItems} />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', borderBottom: '1px solid #f0f0f0' }}>
          <Button type="text" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)} />
          <Dropdown menu={userMenu}>
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#1677ff' }} />
              <span>{user?.username}</span>
            </div>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24, padding: 24, background: '#fff', borderRadius: 8, minHeight: 400 }}>
          <Routes>
            <Route path="/users" element={<UsersPage />} />
            <Route path="/db-configs" element={<DbConfigPage />} />
            <Route path="/snapshots" element={<SnapshotsPage />} />
            <Route path="/comparisons" element={<ComparisonListPage />} />
            <Route path="/comparisons/:id" element={<ComparisonDetailPage />} />
            <Route path="*" element={<Navigate to="/db-configs" />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm,
      token: { borderRadius: 6, colorPrimary: '#1677ff' } }}>
      <AntApp>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/*" element={<AppLayout />} />
        </Routes>
      </AntApp>
    </ConfigProvider>
  );
}
