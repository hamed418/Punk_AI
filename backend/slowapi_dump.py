    def __limit_decorator(
        self,
        limit_value: StrOrCallableStr,
        key_func: Optional[Callable[..., str]] = None,
        shared: bool = False,
        scope: Optional[StrOrCallableStr] = None,
        per_method: bool = False,
        methods: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        exempt_when: Optional[Callable[..., bool]] = None,
        cost: Union[int, Callable[..., int]] = 1,
        override_defaults: bool = True,
    ) -> Callable[..., Any]:
        _scope = scope if shared else None

        def decorator(func: Callable[..., Response]):
            keyfunc = key_func or self._key_func
            name = f"{func.__module__}.{func.__name__}"
            dynamic_limit = None
            static_limits: List[Limit] = []
            if callable(limit_value):
                dynamic_limit = LimitGroup(
                    limit_value,
                    keyfunc,
                    _scope,
                    per_method,
                    methods,
                    error_message,
                    exempt_when,
                    cost,
                    override_defaults,
                )
            else:
                try:
                    static_limits = list(
                        LimitGroup(
                            limit_value,
                            keyfunc,
                            _scope,
                            per_method,
                            methods,
                            error_message,
                            exempt_when,
                            cost,
                            override_defaults,
                        )
                    )
                except ValueError as e:
                    self.logger.error(
                        "Failed to configure throttling for %s (%s)",
                        name,
                        e,
                    )
            self.__marked_for_limiting.setdefault(name, []).append(func)
            if dynamic_limit:
                self._dynamic_route_limits.setdefault(name, []).append(dynamic_limit)
            else:
                self._route_limits.setdefault(name, []).extend(static_limits)

            sig = inspect.signature(func)
            for idx, parameter in enumerate(sig.parameters.values()):
                if parameter.name == "request" or parameter.name == "websocket":
                    break
            else:
                raise Exception(
                    f'No "request" or "websocket" argument on function "{func}"'
                )

            if asyncio.iscoroutinefunction(func):
                # Handle async request/response functions.
                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Response:
                    # get the request object from the decorated endpoint function
                    if self.enabled:
                        request = kwargs.get("request", args[idx] if args else None)
                        if not isinstance(request, Request):
                            raise Exception(
                                "parameter `request` must be an instance of starlette.requests.Request"
                            )

                        if self._auto_check and not getattr(
                            request.state, "_rate_limiting_complete", False
                        ):
                            self._check_request_limit(request, func, False)
                            request.state._rate_limiting_complete = True
                    response = await func(*args, **kwargs)  # type: ignore
                    if self.enabled:
                        if not isinstance(response, Response):
                            # get the response object from the decorated endpoint function
                            self._inject_headers(
                                kwargs.get("response"),  # type: ignore
                                request.state.view_rate_limit,
                            )
                        else:
                            self._inject_headers(
                                response, request.state.view_rate_limit
                            )
                    return response

                return async_wrapper

            else:
                # Handle sync request/response functions.
                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Response:
                    # get the request object from the decorated endpoint function
                    if self.enabled:
                        request = kwargs.get("request", args[idx] if args else None)
                        if not isinstance(request, Request):
                            raise Exception(
                                "parameter `request` must be an instance of starlette.requests.Request"
                            )

                        if self._auto_check and not getattr(
                            request.state, "_rate_limiting_complete", False
                        ):
                            self._check_request_limit(request, func, False)
                            request.state._rate_limiting_complete = True
                    response = func(*args, **kwargs)
                    if self.enabled:
                        if not isinstance(response, Response):
                            # get the response object from the decorated endpoint function
                            self._inject_headers(
                                kwargs.get("response"),
                                request.state.view_rate_limit,  # type: ignore
                            )
                        else:
                            self._inject_headers(
                                response, request.state.view_rate_limit
                            )
                    return response

                return sync_wrapper

        return decorator

