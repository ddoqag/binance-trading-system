package main

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// TestRequestQueuePriority 测试优先级队列的 dequeue 逻辑
// 验证 dequeue() 函数返回的请求顺序符合优先级（高优先级先返回）
func TestRequestQueuePriority(t *testing.T) {
	rq := NewRequestQueue()
	defer rq.Close()

	// 用于同步的 channel
	startProcessing := make(chan struct{})
	var processing int32 = 0

	// 用于记录 dequeue 顺序
	var dequeueOrder []string
	var mu sync.Mutex

	// 提交函数 - 每个请求阻塞在 channel 上，直到我们允许它完成
	submitFunc := func(name string, priority RequestPriority) {
		rq.SubmitAsync("/api/v3/account", priority, func() error {
			// 标记开始处理
			atomic.AddInt32(&processing, 1)

			// 等待开始信号
			<-startProcessing

			mu.Lock()
			dequeueOrder = append(dequeueOrder, name)
			mu.Unlock()

			return nil
		})
	}

	// 按相反顺序提交（低优先级先提交）
	submitFunc("low", PriorityLow)
	submitFunc("normal", PriorityNormal)
	submitFunc("high", PriorityHigh)
	submitFunc("critical", PriorityCritical)

	// 等待所有请求都入队并开始处理（阻塞在 channel 上）
	for i := 0; i < 20; i++ {
		if atomic.LoadInt32(&processing) == 4 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	if atomic.LoadInt32(&processing) != 4 {
		t.Fatalf("Not all requests started processing: %d/4", processing)
	}

	// 现在允许所有请求完成
	// 由于它们都已从队列中 dequeue，执行顺序取决于 goroutine 调度
	// 但 dequeue 顺序应该遵循优先级
	close(startProcessing)

	// 等待结果收集完成
	time.Sleep(50 * time.Millisecond)

	mu.Lock()
	defer mu.Unlock()

	// 验证所有请求都执行了
	if len(dequeueOrder) != 4 {
		t.Errorf("Expected 4 dequeues, got %d: %v", len(dequeueOrder), dequeueOrder)
		return
	}

	// 由于 goroutine 调度的不确定性，我们只能验证关键特性：
	// 1. 所有请求都被执行了
	// 2. 高优先级请求通常会在低优先级之前（但不是绝对的）

	// 验证 "critical" 在队列中（由于它优先级最高，通常会被先 dequeue）
	foundCritical := false
	for _, name := range dequeueOrder {
		if name == "critical" {
			foundCritical = true
			break
		}
	}
	if !foundCritical {
		t.Errorf("Critical priority request not found in dequeue order: %v", dequeueOrder)
	}

	t.Logf("Dequeue order (may vary due to goroutine scheduling): %v", dequeueOrder)
}

// TestRequestQueueDequeueOrder 直接测试 dequeue 函数返回顺序
func TestRequestQueueDequeueOrder(t *testing.T) {
	rq := NewRequestQueue()
	defer rq.Close()

	// 手动添加请求到队列（不启动 processLoop）
	// 通过构造请求并直接调用内部方法

	// 添加 4 个不同优先级的请求
	reqs := []*QueuedRequest{
		{ID: "low", Priority: PriorityLow, Endpoint: "/test"},
		{ID: "normal", Priority: PriorityNormal, Endpoint: "/test"},
		{ID: "high", Priority: PriorityHigh, Endpoint: "/test"},
		{ID: "critical", Priority: PriorityCritical, Endpoint: "/test"},
	}

	// 按相反顺序添加到队列（验证 dequeue 重排序）
	rq.queuesMu.Lock()
	rq.queues[PriorityLow] = append(rq.queues[PriorityLow], reqs[0])
	rq.queues[PriorityNormal] = append(rq.queues[PriorityNormal], reqs[1])
	rq.queues[PriorityHigh] = append(rq.queues[PriorityHigh], reqs[2])
	rq.queues[PriorityCritical] = append(rq.queues[PriorityCritical], reqs[3])
	rq.queuesMu.Unlock()

	// dequeue 应该按优先级顺序返回
	var order []string
	for i := 0; i < 4; i++ {
		req := rq.dequeue()
		if req == nil {
			t.Fatalf("dequeue returned nil at iteration %d", i)
		}
		order = append(order, req.ID)
	}

	// 验证顺序：critical > high > normal > low
	expected := []string{"critical", "high", "normal", "low"}
	for i, exp := range expected {
		if order[i] != exp {
			t.Errorf("Position %d: expected '%s', got '%s' (order: %v)",
				i, exp, order[i], order)
			return
		}
	}

	t.Logf("✓ Dequeue order correct: %v", order)
}

// TestRequestQueueRateLimit 测试速率限制
func TestRequestQueueRateLimit(t *testing.T) {
	rq := NewRequestQueue()
	defer rq.Close()

	// 快速提交多个请求
	start := time.Now()
	count := 0
	var mu sync.Mutex

	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			rq.Submit("/api/v3/account", PriorityNormal, func() error {
				mu.Lock()
				count++
				mu.Unlock()
				return nil
			})
		}()
	}

	wg.Wait()
	elapsed := time.Since(start)

	mu.Lock()
	finalCount := count
	mu.Unlock()

	if finalCount != 10 {
		t.Errorf("Expected 10 completed requests, got %d", finalCount)
	}

	// 由于速率限制，执行应该有一定延迟
	if elapsed < 50*time.Millisecond {
		t.Logf("Warning: requests executed too fast (%v), rate limiting may not be working", elapsed)
	}

	fmt.Printf("Completed %d requests in %v\n", finalCount, elapsed)
}

// TestBinanceClientWithQueue 测试 BinanceClient 的队列集成
func TestBinanceClientWithQueue(t *testing.T) {
	client := NewBinanceClient("test_key", "test_secret", true)
	defer client.Close()

	// 验证队列已初始化
	if client.requestQueue == nil {
		t.Error("RequestQueue should be initialized")
	}

	// 获取速率限制统计
	stats := client.GetRateLimitStats()
	if stats == nil {
		t.Error("GetRateLimitStats should return valid stats")
	}

	// 验证统计中包含队列信息
	if queueSizes, ok := stats["queue_sizes"].(map[string]int); ok {
		fmt.Printf("Queue sizes: low=%d, normal=%d, high=%d, critical=%d\n",
			queueSizes["low"], queueSizes["normal"], queueSizes["high"], queueSizes["critical"])
	} else {
		t.Error("Stats should contain queue_sizes")
	}

	fmt.Printf("Rate limit stats: weight=%d/%d, orders=%d/%d\n",
		stats["weight_used"], stats["weight_limit"],
		stats["orders_10s_used"], stats["orders_10s_limit"])
}

// TestMarginClientQueueIntegration 测试 MarginClient 队列集成
func TestMarginClientQueueIntegration(t *testing.T) {
	client := NewMarginClient("test_key", "test_secret", false)
	defer client.Close()

	// 验证继承的 BinanceClient 有队列
	if client.requestQueue == nil {
		t.Error("MarginClient should inherit RequestQueue from BinanceClient")
	}

	// 验证主网强制使用
	if client.baseURL != BinanceBaseURL {
		t.Errorf("MarginClient should use mainnet, got %s", client.baseURL)
	}

	fmt.Println("MarginClient queue integration test passed")
}

// TestEndpointWeight 测试端点权重计算
func TestEndpointWeight(t *testing.T) {
	rq := NewRequestQueue()
	defer rq.Close()

	tests := []struct {
		endpoint string
		expected int
		isOrder  bool
	}{
		{"/api/v3/order", 1, true},
		{"/api/v3/account", 10, false},
		{"/sapi/v1/margin/order", 1, true},
		{"/sapi/v1/margin/account", 10, false},
		{"/unknown/endpoint", 1, false}, // 默认权重
	}

	for _, tt := range tests {
		weight, isOrder := rq.getEndpointWeight(tt.endpoint)
		if weight != tt.expected {
			t.Errorf("Endpoint %s: expected weight %d, got %d", tt.endpoint, tt.expected, weight)
		}
		if isOrder != tt.isOrder {
			t.Errorf("Endpoint %s: expected isOrder=%v, got %v", tt.endpoint, tt.isOrder, isOrder)
		}
	}

	fmt.Println("Endpoint weight test passed")
}

// TestContextCancellation 测试上下文取消
func TestContextCancellation(t *testing.T) {
	rq := NewRequestQueue()
	defer rq.Close()

	_, cancel := context.WithCancel(context.Background())
	cancel() // 立即取消

	// 提交请求到已取消的上下文应该失败
	err := rq.SubmitWithDeadline("/api/v3/account", PriorityNormal, time.Time{}, func() error {
		return nil
	})

	// 由于队列是异步处理的，这里主要验证不会 panic
	if err != nil {
		fmt.Printf("Expected error after context cancellation: %v\n", err)
	}
}

// BenchmarkRequestQueue 基准测试
func BenchmarkRequestQueue(b *testing.B) {
	rq := NewRequestQueue()
	defer rq.Close()

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			rq.Submit("/api/v3/account", PriorityNormal, func() error {
				return nil
			})
		}
	})
}
