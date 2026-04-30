package com.trading.adapter.shadow;

import java.util.Iterator;
import java.util.NoSuchElementException;
import java.util.function.Consumer;

/**
 * 高性能环形缓冲区 - 用于存储性能快照
 *
 * 特点:
 * 1. 固定容量，自动覆盖旧数据
 * 2. 无锁实现（单生产者）
 * 3. 迭代时保持插入顺序
 */
public class RingBuffer<T> implements Iterable<T> {
    private final Object[] buffer;
    private final int capacity;
    private int head = 0;  // 下次写入位置
    private int size = 0;

    public RingBuffer(int capacity) {
        this.capacity = capacity;
        this.buffer = new Object[capacity];
    }

    public void add(T item) {
        buffer[head] = item;
        head = (head + 1) % capacity;
        if (size < capacity) size++;
    }

    public T get(int index) {
        if (index < 0 || index >= size) {
            throw new IndexOutOfBoundsException("Index: " + index + ", Size: " + size);
        }
        int actualIndex = (head - size + index + capacity) % capacity;
        @SuppressWarnings("unchecked")
        T item = (T) buffer[actualIndex];
        return item;
    }

    public T getLast() {
        if (size == 0) throw new NoSuchElementException();
        return get(size - 1);
    }

    public boolean isEmpty() { return size == 0; }
    public boolean isFull() { return size == capacity; }
    public int size() { return size; }
    public int getCapacity() { return capacity; }

    public void clear() {
        head = 0;
        size = 0;
        for (int i = 0; i < capacity; i++) {
            buffer[i] = null;
        }
    }

    public T[] toArray(T[] array) {
        if (array.length < size) {
            throw new ArrayStoreException("Array too small");
        }
        int j = 0;
        for (T item : this) {
            array[j++] = item;
        }
        return array;
    }

    @Override
    public Iterator<T> iterator() {
        return new Iterator<T>() {
            private int index = 0;

            @Override
            public boolean hasNext() {
                return index < size;
            }

            @Override
            public T next() {
                if (!hasNext()) throw new NoSuchElementException();
                return get(index++);
            }

            @Override
            public void forEachRemaining(Consumer<? super T> action) {
                while (index < size) {
                    action.accept(get(index++));
                }
            }
        };
    }

    @SuppressWarnings("unchecked")
    public java.util.stream.Stream<T> stream() {
        return java.util.Arrays.stream((T[]) java.lang.reflect.Array.newInstance(
            Object.class, size));
    }
}
